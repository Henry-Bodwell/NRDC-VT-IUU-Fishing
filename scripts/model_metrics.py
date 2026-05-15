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

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_lib import (  # noqa: E402
    EXCLUDED_LEAF_NAMES,
    EXCLUDED_LEAVES,
    ApiClient,
    classify_change,
    diff_kde_leaf,
    diff_kde_top_level,
    extract_link_id,
    flatten,
    get_iuu_subtypes,
    get_iuu_types,
    load_ids,
    make_accumulators,
)

logger = logging.getLogger(__name__)


# ── Metric helpers ─────────────────────────────────────────────────────────


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def _prf_raw(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return precision, recall, f1


def prf(tp: int, fp: int, fn: int) -> dict:
    precision, recall, f1 = _prf_raw(tp, fp, fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _macro_avg(per_class_raw: dict[str, tuple[float, float, float, int]]) -> dict:
    """Macro mean over classes with support > 0, computed from unrounded P/R/F1."""
    supported = [v for v in per_class_raw.values() if v[3] > 0]
    if not supported:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "n_classes": 0}
    p = sum(v[0] for v in supported) / len(supported)
    r = sum(v[1] for v in supported) / len(supported)
    f = sum(v[2] for v in supported) / len(supported)
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f, 4),
        "n_classes": len(supported),
    }


def multiclass_metrics(samples: list[tuple[str, str]]) -> dict:
    """Single-label multiclass: each sample is (predicted, truth).

    Returns overall accuracy, per-class P/R/F1, macro avg (over support>0
    classes, computed before rounding), and confusion matrix.
    """
    if not samples:
        return {"n": 0, "accuracy": 0.0, "per_class": {}, "macro": {}, "confusion": {}}

    correct = sum(1 for pred, truth in samples if pred == truth and pred)
    classes = sorted({c for pair in samples for c in pair if c})

    confusion: dict[str, dict[str, int]] = {}
    for pred, truth in samples:
        if truth and pred:
            confusion.setdefault(truth, defaultdict(int))[pred] += 1

    per_class: dict[str, dict] = {}
    per_class_raw: dict[str, tuple[float, float, float, int]] = {}
    for cls in classes:
        tp = sum(1 for pred, truth in samples if pred == cls and truth == cls)
        fp = sum(1 for pred, truth in samples if pred == cls and truth != cls)
        fn = sum(1 for pred, truth in samples if pred != cls and truth == cls)
        support = sum(1 for _, truth in samples if truth == cls)
        prec, rec, f1 = _prf_raw(tp, fp, fn)
        per_class[cls] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": support,
        }
        per_class_raw[cls] = (prec, rec, f1, support)

    return {
        "n": len(samples),
        "accuracy": round(_safe_div(correct, len(samples)), 4),
        "per_class": per_class,
        "macro": _macro_avg(per_class_raw),
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }


def multilabel_metrics(samples: list[tuple[set[str], set[str]]]) -> dict:
    """Each sample is (predicted_labels, truth_labels). Computes micro/macro P/R/F1.

    Macro avg is over classes with support>0 and computed from unrounded P/R/F1.
    """
    if not samples:
        return {"n": 0, "micro": {}, "macro": {}, "per_class": {}}

    classes = sorted({lbl for p, t in samples for lbl in p | t})
    per_class: dict[str, dict] = {}
    per_class_raw: dict[str, tuple[float, float, float, int]] = {}
    micro_tp = micro_fp = micro_fn = 0
    for cls in classes:
        tp = sum(1 for p, t in samples if cls in p and cls in t)
        fp = sum(1 for p, t in samples if cls in p and cls not in t)
        fn = sum(1 for p, t in samples if cls not in p and cls in t)
        support = sum(1 for _, t in samples if cls in t)
        prec, rec, f1 = _prf_raw(tp, fp, fn)
        per_class[cls] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": support,
        }
        per_class_raw[cls] = (prec, rec, f1, support)
        micro_tp += tp
        micro_fp += fp
        micro_fn += fn

    exact_match = sum(1 for p, t in samples if p == t)

    return {
        "n": len(samples),
        "exact_match_rate": round(_safe_div(exact_match, len(samples)), 4),
        "micro": prf(micro_tp, micro_fp, micro_fn),
        "macro": _macro_avg(per_class_raw),
        "per_class": per_class,
    }


def kde_rates(kde_bucket: dict) -> dict:
    """Compute precision / recall / F1 per field from raw slot-judgment buckets.

    Treats each (incident, field) as a slot-filling judgment with five
    outcomes (see classify_change in _review_lib): correct, correct_empty,
    missing, spurious, mismatch. Mismatches are scored strictly — they count
    as both FP and FN. `correct_empty` (pred and truth both empty) is counted
    as a successful prediction (TP) so fields the model correctly identifies
    as empty don't drag scores to zero.

    Reported rates per field (with tp_eff = correct + correct_empty):
      - precision = tp_eff / (tp_eff + spurious + mismatch)
      - recall    = tp_eff / (tp_eff + missing  + mismatch)
      - f1        = harmonic mean of the above
      - mismatch_rate  = mismatch / (correct + mismatch)
        ("when both pred and gold said the slot was populated, how often did
         the value disagree?")
      - miss_rate      = missing  / (tp_eff + missing  + mismatch)   # FN-rate
      - spurious_rate  = spurious / (tp_eff + spurious + mismatch)   # FP-rate
    """
    out = {}
    for field, b in kde_bucket.items():
        correct = b.get("correct", 0)
        correct_empty = b.get("correct_empty", 0)
        missing = b.get("missing", 0)
        spurious = b.get("spurious", 0)
        mismatch = b.get("mismatch", 0)

        tp_eff = correct + correct_empty
        n_judgments = correct + correct_empty + missing + spurious + mismatch
        support = tp_eff + missing + mismatch
        n_predicted = tp_eff + spurious + mismatch

        prec, rec, f1 = _prf_raw(tp_eff, spurious + mismatch, missing + mismatch)
        out[field] = {
            **dict(b),
            "n_judgments": n_judgments,
            "support": support,
            "n_predicted": n_predicted,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "mismatch_rate": round(_safe_div(mismatch, correct + mismatch), 4),
            "miss_rate": round(_safe_div(missing, support), 4),
            "spurious_rate": round(_safe_div(spurious, n_predicted), 4),
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
    vessel = (
        ((inc.get("vesselInformation") or {}).get("vesselName") or "").strip().lower()
    )
    event = (inc.get("eventData") or {}).get("eventDate") or ""
    if vessel or event:
        return f"{vessel}|{event}"
    return json.dumps(inc, sort_keys=True, default=str)


def _str_key(c: Any) -> str:
    """Lowercase-trim a list entry; fall back to canonical JSON for non-strings."""
    if c is None:
        return ""
    if isinstance(c, str):
        return c.strip().lower()
    return json.dumps(c, sort_keys=True, default=str).strip().lower()


_LIST_KEYS: dict[str, Any] = {
    "species": _species_key,
    "countries": _str_key,
    "companies": _str_key,
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
    out = {
        "list_fields": {},
        "summary": dict(acc["overview"]["summary"]),
        "counts": dict(acc["overview"]["counts"]),
    }
    for field, block in acc["overview"]["list_fields"].items():
        out["list_fields"][field] = {
            **block,
            **prf(block["tp"], block["fp"], block["fn"]),
        }
    return out


# ── Accumulators ───────────────────────────────────────────────────────────


def _incident_leaf_accuracy(orig: dict, curr: dict) -> float | None:
    """Strict per-incident accuracy across leaf KDE fields.

    Returns (correct + correct_empty) / total_leaf_judgments, or None when the
    incident contributes no judgments. Mirrors the field selection used by
    diff_kde_leaf so the histogram lines up with the aggregate kde_leaf metrics.
    """
    orig_flat = dict(flatten(orig.get("extracted_information") or {}))
    curr_flat = dict(flatten(curr.get("extracted_information") or {}))
    correct = 0
    total = 0
    for key in set(orig_flat) | set(curr_flat):
        if key in EXCLUDED_LEAVES:
            continue
        if key.rsplit(".", 1)[-1] in EXCLUDED_LEAF_NAMES:
            continue
        bucket = classify_change(orig_flat.get(key), curr_flat.get(key))
        total += 1
        if bucket in ("correct", "correct_empty"):
            correct += 1
    if total == 0:
        return None
    return correct / total


def make_metric_accumulators() -> dict:
    """Extended accumulator: review_analysis buckets + per-sample lists for metrics."""
    acc = make_accumulators()
    acc["counts"]["sources_v1_missing"] = 0
    acc["per_incident_accuracy"] = []
    acc["samples"] = {
        "scope": [],  # list of (pred, truth)
        "iuu_type": [],  # list of (set, set)
        "iuu_subtype": [],  # list of (set, set)
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


_SCOPE_REMAP = {
    "Single Incident": "Incidents",
    "Multiple Incidents": "Incidents",
    "Industry Overview": "Related to IUU+, no incident",
    "Unrelated": "Unrelated",
}


def _normalize_scope(label: str) -> str:
    return _SCOPE_REMAP.get(label, label)


def _scope_of(state: dict | None) -> str:
    if not state:
        return "<missing>"
    scope = state.get("article_scope") or {}
    return _normalize_scope(scope.get("articleType") or "<none>")


async def run(
    ids_file: Path,
    output: Path,
    base_url: str,
    auth_token: str | None,
    figures_dir: Path | None = None,
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
            if not v1_state:
                acc["counts"]["sources_v1_missing"] += 1
                acc["skipped"].append({"id": raw_id, "reason": "source_no_v1_state"})
                logger.warning("Source %s has no v1 state; skipping entirely", raw_id)
                continue

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
                        if isinstance(ov_link, dict)
                        and "extracted_information" in ov_link
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
                inc_acc = _incident_leaf_accuracy(inc_v1, curr)
                if inc_acc is not None:
                    acc["per_incident_accuracy"].append(inc_acc)
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

    if figures_dir is not None:
        write_figures(metrics, figures_dir, acc["per_incident_accuracy"])
        logger.info("Wrote confusion-matrix figures to %s", figures_dir)


# ── Figures ────────────────────────────────────────────────────────────────


def _wrap(s: str, width: int = 22) -> str:
    import textwrap

    return "\n".join(textwrap.wrap(s, width=width)) or s


def plot_scope_confusion(scope_metrics: dict, out: Path) -> None:
    """Render the multiclass scope confusion matrix as a heatmap.

    Rows are truth labels, columns are predicted labels. Cells annotated with
    raw counts; an unnormalized colormap is used so empty cells stand out.
    """
    confusion = scope_metrics.get("confusion") or {}
    if not confusion:
        return

    labels = sorted(
        {k for k in confusion} | {p for row in confusion.values() for p in row}
    )
    n = len(labels)
    idx = {lbl: i for i, lbl in enumerate(labels)}
    mat = np.zeros((n, n), dtype=int)
    for truth, preds in confusion.items():
        for pred, count in preds.items():
            mat[idx[truth]][idx[pred]] = count

    wrapped = [_wrap(lbl) for lbl in labels]
    side = max(5.0, 0.9 * n + 3.0)
    fig, ax = plt.subplots(figsize=(side, side))
    masked = np.ma.masked_where(mat == 0, mat)
    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad(color="whitesmoke")
    im = ax.imshow(masked, cmap=cmap)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(wrapped, rotation=40, ha="right", fontsize=9)
    ax.set_yticklabels(wrapped, fontsize=9)
    ax.set_xlabel("Predicted (v1)")
    ax.set_ylabel("Truth (current)")
    vmax = int(mat.max()) if mat.max() > 0 else 1
    threshold = vmax * 0.55
    for i in range(n):
        for j in range(n):
            val = mat[i][j]
            if val:
                color = "white" if val > threshold else "black"
                ax.text(
                    j, i, str(val), ha="center", va="center", color=color, fontsize=9
                )
    ax.set_title(
        f"Scope confusion matrix  (n={scope_metrics['n']}, "
        f"accuracy={scope_metrics['accuracy']})"
    )
    fig.colorbar(im, ax=ax, shrink=0.7, label="count")
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_multilabel_confusions(
    name: str, ml_metrics: dict, out: Path, max_classes: int = 24
) -> None:
    """Render per-class 2x2 confusion matrices for a multilabel classifier.

    Each panel: rows = truth (present/absent), cols = pred (present/absent).
    TN = n_samples - TP - FP - FN. Classes are sorted by support, descending.
    """
    per_class = ml_metrics.get("per_class") or {}
    if not per_class:
        return
    n_samples = ml_metrics.get("n", 0)

    classes = sorted(per_class.items(), key=lambda kv: -kv[1].get("support", 0))[
        :max_classes
    ]
    if not classes:
        return

    n = len(classes)
    cols = min(4, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(3.4 * cols, 3.2 * rows))
    axes = np.array(axes).reshape(rows, cols)

    cmap = plt.get_cmap("Blues")
    for k, (cls, m) in enumerate(classes):
        r, c = divmod(k, cols)
        ax = axes[r][c]
        tp, fp, fn = m["tp"], m["fp"], m["fn"]
        tn = max(0, n_samples - tp - fp - fn)
        # rows = truth (+/-), cols = pred (+/-)
        mat = np.array([[tp, fn], [fp, tn]])
        ax.imshow(mat, cmap=cmap, vmin=0, vmax=max(mat.max(), 1))
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(["pred +", "pred -"], fontsize=8)
        ax.set_yticklabels(["truth +", "truth -"], fontsize=8)
        threshold = mat.max() * 0.55 if mat.max() else 1
        cell_labels = [["TP", "FN"], ["FP", "TN"]]
        for i in range(2):
            for j in range(2):
                val = mat[i][j]
                color = "white" if val > threshold else "black"
                ax.text(
                    j,
                    i,
                    f"{cell_labels[i][j]}\n{val}",
                    ha="center",
                    va="center",
                    color=color,
                    fontsize=9,
                )
        ax.set_title(
            f"{_wrap(cls, width=28)}\nP={m['precision']} R={m['recall']} "
            f"F1={m['f1']} (sup={m['support']})",
            fontsize=8,
        )
    for k in range(n, rows * cols):
        r, c = divmod(k, cols)
        axes[r][c].axis("off")

    fig.suptitle(
        f"{name} per-class confusion (n_samples={n_samples}, "
        f"top {len(classes)} by support)",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_incident_accuracy_distribution(
    accuracies: list[float], out: Path, bins: int = 20
) -> None:
    """Histogram of per-incident leaf-field accuracy."""
    if not accuracies:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(
        accuracies,
        bins=bins,
        range=(0.0, 1.0),
        color="steelblue",
        edgecolor="white",
    )
    median = float(np.median(accuracies))
    mean = float(np.mean(accuracies))
    ax.axvline(
        median,
        color="black",
        linestyle="--",
        linewidth=1,
        label=f"median = {median:.3f}",
    )
    ax.axvline(
        mean,
        color="firebrick",
        linestyle=":",
        linewidth=1,
        label=f"mean = {mean:.3f}",
    )
    ax.set_xlabel(
        "Per-incident accuracy  (correct + correct_empty) / total leaf judgments"
    )
    ax.set_ylabel("Count of incidents")
    ax.set_title(f"Distribution of extraction quality  (n = {len(accuracies)})")
    ax.set_xlim(0.0, 1.0)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_figures(
    metrics: dict, figures_dir: Path, per_incident_accuracy: list[float]
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    plot_scope_confusion(metrics["scope"], figures_dir / "scope_confusion.png")
    plot_multilabel_confusions(
        "IUU type", metrics["iuu_type"], figures_dir / "iuu_type_confusion.png"
    )
    plot_multilabel_confusions(
        "IUU subtype",
        metrics["iuu_subtype"],
        figures_dir / "iuu_subtype_confusion.png",
    )
    plot_incident_accuracy_distribution(
        per_incident_accuracy,
        figures_dir / "incident_accuracy_distribution.png",
    )


# ── Reporting ──────────────────────────────────────────────────────────────


def print_summary(acc: dict, metrics: dict) -> None:
    c = acc["counts"]
    print("\n=== Run summary ===")
    print(
        f"Sources processed: {c['sources_processed']}  "
        f"missing: {c['sources_missing']}  "
        f"v1_missing: {c.get('sources_v1_missing', 0)}"
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
    print(
        f"  macro: P={sm['macro'].get('precision', 0)} "
        f"R={sm['macro'].get('recall', 0)} F1={sm['macro'].get('f1', 0)}"
    )
    print(f"  {'class':<30} {'P':>6} {'R':>6} {'F1':>6} {'support':>8}")
    for cls, m in sm["per_class"].items():
        print(
            f"  {cls:<30} {m['precision']:>6} {m['recall']:>6} "
            f"{m['f1']:>6} {m['support']:>8}"
        )

    print("\n=== B. IUU type (multilabel) ===")
    bm = metrics["iuu_type"]
    print(f"  n={bm['n']}  exact_match_rate={bm.get('exact_match_rate')}")
    if bm.get("micro"):
        print(
            f"  micro: P={bm['micro']['precision']} R={bm['micro']['recall']} "
            f"F1={bm['micro']['f1']}"
        )
        print(
            f"  macro: P={bm['macro']['precision']} R={bm['macro']['recall']} "
            f"F1={bm['macro']['f1']}"
        )
    for cls, m in bm.get("per_class", {}).items():
        print(
            f"    {cls:<45} P={m['precision']:>6} R={m['recall']:>6} "
            f"F1={m['f1']:>6} support={m['support']}"
        )

    print("\n=== C. IUU subtype (multilabel) ===")
    cm = metrics["iuu_subtype"]
    print(f"  n={cm['n']}  exact_match_rate={cm.get('exact_match_rate')}")
    if cm.get("micro"):
        print(
            f"  micro: P={cm['micro']['precision']} R={cm['micro']['recall']} "
            f"F1={cm['micro']['f1']}"
        )
        print(
            f"  macro: P={cm['macro']['precision']} R={cm['macro']['recall']} "
            f"F1={cm['macro']['f1']}"
        )

    print("\n=== D. KDE top-level (worst 10 by F1, support>0 only) ===")
    top = sorted(
        (kv for kv in metrics["kde_top"].items() if kv[1].get("support", 0) > 0),
        key=lambda kv: kv[1].get("f1", 0),
    )
    print(
        f"  {'field':<32} {'P':>6} {'R':>6} {'F1':>6} "
        f"{'mismatch%':>10} {'support':>8}"
    )
    for field, m in top:
        print(
            f"  {field:<32} {m['precision']:>6} {m['recall']:>6} "
            f"{m['f1']:>6} {m['mismatch_rate']:>10} {m['support']:>8}"
        )

    print("\n=== E. Industry Overview ===")
    ov = metrics["overview"]
    for field, m in ov["list_fields"].items():
        print(
            f"  {field:<12} P={m['precision']:>6} R={m['recall']:>6} "
            f"F1={m['f1']:>6} (tp={m['tp']} fp={m['fp']} fn={m['fn']})"
        )
    print(f"  summary buckets: {ov['summary']}")


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
        "per_incident_accuracy": acc["per_incident_accuracy"],
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
        default=Path("scripts/data/model_metrics.json"),
        help="Path for detailed JSON output",
    )
    parser.add_argument(
        "--figures-dir",
        type=str,
        default="scripts/figures/model_metrics",
        help="Directory to write confusion-matrix PNGs (pass empty string to skip).",
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

    figures_dir = Path(args.figures_dir) if args.figures_dir else None
    asyncio.run(
        run(
            args.ids_file,
            args.output,
            args.base_url,
            args.auth_token,
            figures_dir,
        )
    )


if __name__ == "__main__":
    main()
