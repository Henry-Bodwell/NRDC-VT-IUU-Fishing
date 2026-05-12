"""Compute accuracy / precision / recall / F1 for the production pipeline.

Treats the current human-reviewed DB state as ground truth and the v1 state
(initial model extraction, from /api/logs/{id}/version/1) as the prediction.
Extends scripts/review_analysis.py with:

  * Classifier metrics for scope (multiclass), IUU type and IUU subtype
    (both multilabel) including per-class precision/recall/F1 + confusion matrix.
  * KDE field-activity rates (missed_rate, change_rate) in addition to raw counts.
  * Industry Overview verification: when a source's scope is "Industry Overview",
    diff the linked IndustryOverview.extracted_information (species, countries,
    companies, incidents, summary) v1-vs-current using set-membership P/R for
    lists and bucket counts for free-text summary.

Usage:
    python scripts/model_metrics.py \
        --ids-file source_ids.json \
        --base-url http://localhost:8000 \
        --auth-token "$AUTH_TOKEN" \
        --output scripts/model_metrics.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_lib import (  # noqa: E402
    ApiClient,
    classify_change,
    diff_kde_leaf,
    diff_kde_top_level,
    extract_link_id,
    get_iuu_subtypes,
    get_iuu_types,
    load_ids,
    make_accumulators,
)

logger = logging.getLogger(__name__)


# ── Metric helpers ─────────────────────────────────────────────────────────

def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def prf(tp: int, fp: int, fn: int) -> dict:
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def multiclass_metrics(samples: list[tuple[str, str]]) -> dict:
    """Single-label multiclass: each sample is (predicted, truth).

    Returns overall accuracy, per-class P/R/F1, macro avg, and confusion matrix.
    """
    if not samples:
        return {"n": 0, "accuracy": 0.0, "per_class": {}, "macro": {}, "confusion": {}}

    correct = sum(1 for pred, truth in samples if pred == truth)
    classes = sorted({c for pair in samples for c in pair if c})

    per_class = {}
    confusion: dict[str, dict[str, int]] = {
        truth: defaultdict(int) for truth in classes
    }
    for pred, truth in samples:
        if truth and pred:
            confusion.setdefault(truth, defaultdict(int))[pred] += 1

    for cls in classes:
        tp = sum(1 for pred, truth in samples if pred == cls and truth == cls)
        fp = sum(1 for pred, truth in samples if pred == cls and truth != cls)
        fn = sum(1 for pred, truth in samples if pred != cls and truth == cls)
        support = sum(1 for _, truth in samples if truth == cls)
        per_class[cls] = {**prf(tp, fp, fn), "support": support}

    macro_p = _safe_div(sum(c["precision"] for c in per_class.values()), len(per_class))
    macro_r = _safe_div(sum(c["recall"] for c in per_class.values()), len(per_class))
    macro_f = _safe_div(sum(c["f1"] for c in per_class.values()), len(per_class))

    return {
        "n": len(samples),
        "accuracy": round(_safe_div(correct, len(samples)), 4),
        "per_class": per_class,
        "macro": {
            "precision": round(macro_p, 4),
            "recall": round(macro_r, 4),
            "f1": round(macro_f, 4),
        },
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }


def multilabel_metrics(samples: list[tuple[set[str], set[str]]]) -> dict:
    """Each sample is (predicted_labels, truth_labels). Computes micro/macro P/R/F1."""
    if not samples:
        return {"n": 0, "micro": {}, "macro": {}, "per_class": {}}

    classes = sorted({lbl for p, t in samples for lbl in p | t})
    per_class = {}
    micro_tp = micro_fp = micro_fn = 0
    for cls in classes:
        tp = sum(1 for p, t in samples if cls in p and cls in t)
        fp = sum(1 for p, t in samples if cls in p and cls not in t)
        fn = sum(1 for p, t in samples if cls not in p and cls in t)
        support = sum(1 for _, t in samples if cls in t)
        per_class[cls] = {**prf(tp, fp, fn), "support": support}
        micro_tp += tp
        micro_fp += fp
        micro_fn += fn

    macro_p = _safe_div(sum(c["precision"] for c in per_class.values()), len(per_class))
    macro_r = _safe_div(sum(c["recall"] for c in per_class.values()), len(per_class))
    macro_f = _safe_div(sum(c["f1"] for c in per_class.values()), len(per_class))

    exact_match = sum(1 for p, t in samples if p == t)

    return {
        "n": len(samples),
        "exact_match_rate": round(_safe_div(exact_match, len(samples)), 4),
        "micro": prf(micro_tp, micro_fp, micro_fn),
        "macro": {
            "precision": round(macro_p, 4),
            "recall": round(macro_r, 4),
            "f1": round(macro_f, 4),
        },
        "per_class": per_class,
    }


def kde_rates(kde_bucket: dict) -> dict:
    """Compute missed_rate / change_rate / removed_rate per field from raw counters."""
    out = {}
    for field, b in kde_bucket.items():
        untouched = b.get("untouched", 0)
        missed = b.get("missed", 0)
        changed = b.get("changed", 0)
        removed = b.get("removed", 0)
        truth_populated = changed + removed + untouched  # populated_in_truth - missed
        # populated_in_truth = (populated in both = changed + untouched) + (missed)
        # actually:
        # untouched = empty in both OR equal in both
        # We don't separate "empty in both" from "equal", so this is an approximation.
        total = untouched + missed + changed + removed
        any_touch = missed + changed + removed
        out[field] = {
            **dict(b),
            "total": total,
            "missed_rate": round(_safe_div(missed, total), 4),
            "change_rate": round(_safe_div(any_touch, total), 4),
            "removed_rate": round(_safe_div(removed, total), 4),
        }
    return out


# ── Industry Overview diffing ──────────────────────────────────────────────

def _species_key(s: dict) -> str:
    sci = (s or {}).get("scientificName") or ""
    common = (s or {}).get("speciesCommonName") or ""
    return f"{sci.strip().lower()}|{common.strip().lower()}"


def _incident_key(inc: dict) -> str:
    """Stable key for an extracted incident in an overview.

    Falls back through vessel/event-date to a canonical JSON dump.
    """
    if not isinstance(inc, dict):
        return json.dumps(inc, sort_keys=True, default=str)
    vessel = ((inc.get("vesselInformation") or {}).get("vesselName") or "").strip().lower()
    event = ((inc.get("eventData") or {}).get("eventDate") or "")
    if vessel or event:
        return f"{vessel}|{event}"
    return json.dumps(inc, sort_keys=True, default=str)


_LIST_KEYS: dict[str, Any] = {
    "species": _species_key,
    "countries": lambda c: (c or "").strip().lower(),
    "companies": lambda c: (c or "").strip().lower(),
    "incidents": _incident_key,
}


def diff_overview(v1: dict, curr: dict, acc: dict) -> None:
    """Compare two IndustryOverview.extracted_information dicts.

    Updates the `overview` block in acc with:
      - per-field set-membership counts (tp/fp/fn) for list fields
      - summary bucket counts (untouched / missed / changed / removed)
    """
    v1_ext = v1.get("extracted_information") or {}
    curr_ext = curr.get("extracted_information") or {}

    for field, key_fn in _LIST_KEYS.items():
        pred = {key_fn(x) for x in (v1_ext.get(field) or [])}
        truth = {key_fn(x) for x in (curr_ext.get(field) or [])}
        block = acc["overview"]["list_fields"][field]
        block["tp"] += len(pred & truth)
        block["fp"] += len(pred - truth)
        block["fn"] += len(truth - pred)
        block["n_predicted"] += len(pred)
        block["n_truth"] += len(truth)

    bucket = classify_change(v1_ext.get("summary"), curr_ext.get("summary"))
    acc["overview"]["summary"][bucket] += 1
    acc["overview"]["counts"]["overviews_processed"] += 1


def overview_summary(acc: dict) -> dict:
    out = {"list_fields": {}, "summary": dict(acc["overview"]["summary"]),
           "counts": dict(acc["overview"]["counts"])}
    for field, block in acc["overview"]["list_fields"].items():
        out["list_fields"][field] = {
            **block,
            **prf(block["tp"], block["fp"], block["fn"]),
        }
    return out


# ── Accumulators ───────────────────────────────────────────────────────────

def make_metric_accumulators() -> dict:
    """Extended accumulator: review_analysis buckets + per-sample lists for metrics."""
    acc = make_accumulators()
    acc["samples"] = {
        "scope": [],          # list of (pred, truth)
        "iuu_type": [],       # list of (set, set)
        "iuu_subtype": [],    # list of (set, set)
    }
    acc["overview"] = {
        "list_fields": {
            k: {"tp": 0, "fp": 0, "fn": 0, "n_predicted": 0, "n_truth": 0}
            for k in _LIST_KEYS
        },
        "summary": Counter(),
        "counts": {"overviews_processed": 0, "overviews_skipped": 0},
    }
    return acc


# ── Main runner ────────────────────────────────────────────────────────────

def _scope_of(state: dict | None) -> str:
    if not state:
        return "<missing>"
    scope = state.get("article_scope") or {}
    return scope.get("articleType") or "<none>"


async def run(
    ids_file: Path, output: Path, base_url: str, auth_token: str | None
) -> None:
    ids = load_ids(ids_file)
    logger.info("Loaded %d source IDs", len(ids))

    acc = make_metric_accumulators()
    seen_incidents: set[str] = set()
    seen_overviews: set[str] = set()
    api = ApiClient(base_url, auth_token)
    try:
        for raw_id in ids:
            source = await api.get_source(raw_id)
            if not source:
                acc["counts"]["sources_missing"] += 1
                acc["skipped"].append({"id": raw_id, "reason": "source_not_found"})
                continue

            v1_state = await api.get_v1_state(raw_id)
            # Scope: predicted = v1, truth = current
            pred_scope = _scope_of(v1_state)
            truth_scope = _scope_of(source)
            acc["source_scope"][(pred_scope, truth_scope)] += 1
            acc["samples"]["scope"].append((pred_scope, truth_scope))
            acc["counts"]["sources_processed"] += 1

            # Industry overview
            ov_link = source.get("overview")
            if ov_link:
                overview_id = extract_link_id(ov_link)
                if overview_id and overview_id not in seen_overviews:
                    seen_overviews.add(overview_id)
                    curr_ov = (
                        ov_link
                        if isinstance(ov_link, dict) and "extracted_information" in ov_link
                        else await api.get_overview(overview_id)
                    )
                    if not curr_ov:
                        acc["overview"]["counts"]["overviews_skipped"] += 1
                        acc["skipped"].append(
                            {"id": overview_id, "reason": "overview_not_found"}
                        )
                    else:
                        ov_v1 = await api.get_v1_state(overview_id)
                        if not ov_v1:
                            acc["overview"]["counts"]["overviews_skipped"] += 1
                            acc["skipped"].append(
                                {"id": overview_id, "reason": "no_v1_state"}
                            )
                        else:
                            diff_overview(ov_v1, curr_ov, acc)

            for link in source.get("incidents") or []:
                incident_id = extract_link_id(link)
                if not incident_id or incident_id in seen_incidents:
                    continue
                seen_incidents.add(incident_id)

                if isinstance(link, dict) and "extracted_information" in link:
                    curr = link
                else:
                    curr = await api.get_incident(incident_id)
                    if not curr:
                        acc["counts"]["incidents_skipped"] += 1
                        acc["skipped"].append(
                            {"id": incident_id, "reason": "incident_not_found"}
                        )
                        continue

                inc_v1 = await api.get_v1_state(incident_id)
                if not inc_v1:
                    acc["counts"]["incidents_skipped"] += 1
                    acc["skipped"].append({"id": incident_id, "reason": "no_v1_state"})
                    continue

                # Per-sample for multilabel metrics: predicted = v1, truth = current
                pred_types = get_iuu_types(inc_v1.get("incident_classification"))
                truth_types = get_iuu_types(curr.get("incident_classification"))
                acc["samples"]["iuu_type"].append((pred_types, truth_types))

                pred_subs = get_iuu_subtypes(inc_v1.get("incident_classification"))
                truth_subs = get_iuu_subtypes(curr.get("incident_classification"))
                acc["samples"]["iuu_subtype"].append((pred_subs, truth_subs))

                # Per-class transition counters (compat with review_analysis output)
                if pred_types == truth_types:
                    acc["iuu_type_unchanged"] += 1
                else:
                    for added in truth_types - pred_types:
                        acc["iuu_type_added"][added] += 1
                    for removed in pred_types - truth_types:
                        acc["iuu_type_removed"][removed] += 1
                if pred_subs == truth_subs:
                    acc["iuu_subtype_unchanged"] += 1
                else:
                    for added in truth_subs - pred_subs:
                        acc["iuu_subtype_added"][added] += 1
                    for removed in pred_subs - truth_subs:
                        acc["iuu_subtype_removed"][removed] += 1

                diff_kde_top_level(inc_v1, curr, acc)
                diff_kde_leaf(inc_v1, curr, acc)
                acc["counts"]["incidents_processed"] += 1
    finally:
        await api.aclose()

    metrics = {
        "scope": multiclass_metrics(acc["samples"]["scope"]),
        "iuu_type": multilabel_metrics(acc["samples"]["iuu_type"]),
        "iuu_subtype": multilabel_metrics(acc["samples"]["iuu_subtype"]),
        "kde_top": kde_rates(acc["kde_top"]),
        "kde_leaf": kde_rates(acc["kde_leaf"]),
        "overview": overview_summary(acc),
    }

    print_summary(acc, metrics)
    write_json(acc, metrics, output)
    logger.info("Wrote detailed JSON to %s", output)


# ── Reporting ──────────────────────────────────────────────────────────────

def print_summary(acc: dict, metrics: dict) -> None:
    c = acc["counts"]
    print("\n=== Run summary ===")
    print(
        f"Sources processed: {c['sources_processed']}  "
        f"missing: {c['sources_missing']}"
    )
    print(
        f"Incidents processed: {c['incidents_processed']}  "
        f"skipped: {c['incidents_skipped']}"
    )
    ov_c = acc["overview"]["counts"]
    print(
        f"Overviews processed: {ov_c['overviews_processed']}  "
        f"skipped: {ov_c['overviews_skipped']}"
    )

    print("\n=== A. Scope classifier ===")
    sm = metrics["scope"]
    print(f"  n={sm['n']}  accuracy={sm['accuracy']}")
    print(f"  macro: P={sm['macro'].get('precision', 0)} "
          f"R={sm['macro'].get('recall', 0)} F1={sm['macro'].get('f1', 0)}")
    print(f"  {'class':<30} {'P':>6} {'R':>6} {'F1':>6} {'support':>8}")
    for cls, m in sm["per_class"].items():
        print(f"  {cls:<30} {m['precision']:>6} {m['recall']:>6} "
              f"{m['f1']:>6} {m['support']:>8}")

    print("\n=== B. IUU type (multilabel) ===")
    bm = metrics["iuu_type"]
    print(f"  n={bm['n']}  exact_match_rate={bm.get('exact_match_rate')}")
    if bm.get("micro"):
        print(f"  micro: P={bm['micro']['precision']} R={bm['micro']['recall']} "
              f"F1={bm['micro']['f1']}")
        print(f"  macro: P={bm['macro']['precision']} R={bm['macro']['recall']} "
              f"F1={bm['macro']['f1']}")
    for cls, m in bm.get("per_class", {}).items():
        print(f"    {cls:<45} P={m['precision']:>6} R={m['recall']:>6} "
              f"F1={m['f1']:>6} support={m['support']}")

    print("\n=== C. IUU subtype (multilabel) ===")
    cm = metrics["iuu_subtype"]
    print(f"  n={cm['n']}  exact_match_rate={cm.get('exact_match_rate')}")
    if cm.get("micro"):
        print(f"  micro: P={cm['micro']['precision']} R={cm['micro']['recall']} "
              f"F1={cm['micro']['f1']}")
        print(f"  macro: P={cm['macro']['precision']} R={cm['macro']['recall']} "
              f"F1={cm['macro']['f1']}")

    print("\n=== D. KDE top-level (top 10 by change_rate) ===")
    top = sorted(
        metrics["kde_top"].items(), key=lambda kv: -kv[1].get("change_rate", 0)
    )[:10]
    print(f"  {'field':<32} {'changed%':>10} {'missed%':>10} {'removed%':>10}")
    for field, m in top:
        print(f"  {field:<32} {m['change_rate']:>10} {m['missed_rate']:>10} "
              f"{m['removed_rate']:>10}")

    print("\n=== E. Industry Overview ===")
    ov = metrics["overview"]
    for field, m in ov["list_fields"].items():
        print(f"  {field:<12} P={m['precision']:>6} R={m['recall']:>6} "
              f"F1={m['f1']:>6} (tp={m['tp']} fp={m['fp']} fn={m['fn']})")
    print(f"  summary buckets: {dict(ov['summary'])}")


def write_json(acc: dict, metrics: dict, path: Path) -> None:
    serializable = {
        "counts": acc["counts"],
        "source_scope": [
            {"original": orig, "current": curr, "count": count}
            for (orig, curr), count in sorted(
                acc["source_scope"].items(), key=lambda x: -x[1]
            )
        ],
        "iuu_type": {
            "unchanged": acc["iuu_type_unchanged"],
            "added": dict(acc["iuu_type_added"]),
            "removed": dict(acc["iuu_type_removed"]),
        },
        "iuu_subtype": {
            "unchanged": acc["iuu_subtype_unchanged"],
            "added": dict(acc["iuu_subtype_added"]),
            "removed": dict(acc["iuu_subtype_removed"]),
        },
        "kde_top": {k: dict(v) for k, v in acc["kde_top"].items()},
        "kde_leaf": {k: dict(v) for k, v in acc["kde_leaf"].items()},
        "skipped": acc["skipped"],
        "metrics": metrics,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ids-file", required=True, type=Path, help="JSON/CSV file of Source IDs"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://localhost:8000"),
        help="API base URL (default: http://localhost:8000 or $API_BASE_URL)",
    )
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("AUTH_TOKEN"),
        help="Admin bearer token (or set AUTH_TOKEN env var). /api/logs requires it.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scripts/model_metrics.json"),
        help="Path for detailed JSON output",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.auth_token:
        logger.warning(
            "No auth token provided; /api/logs calls will likely 401. "
            "Pass --auth-token or set AUTH_TOKEN."
        )

    asyncio.run(run(args.ids_file, args.output, args.base_url, args.auth_token))


if __name__ == "__main__":
    main()
