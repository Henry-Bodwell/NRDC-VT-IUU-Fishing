"""Naive single-shot baseline extractor — used to evaluate the production pipeline.

The point of this script is to measure how much the multi-stage
`AnalysisPipeline` (presence-detection -> conditional-extraction -> separate
classification) actually helps. It deliberately does NOT use any code from
`app.dspy_files`: it makes two raw chat-completions per source (one to
classify scope, one to classify + extract) using a configurable model, then
diffs the result against the current reviewed DB state.

A grep for "from app.dspy_files" in this file must return zero matches —
that structural absence is the evaluation guarantee.

Usage:
    python scripts/baseline_extraction.py \
        --ids-file source_ids.json \
        --base-url http://localhost:8000 \
        --auth-token "$AUTH_TOKEN" \
        --model openai/gpt-4o-mini \
        --output-dir scripts/baseline_runs/gpt4o-mini \
        --metrics-output scripts/baseline_metrics_gpt4o-mini.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dspy  # transport only — NOT the pipeline  # noqa: E402

from _progress_db import ProgressDB  # noqa: E402
from _review_lib import (  # noqa: E402
    ApiClient,
    diff_kde_leaf,
    diff_kde_top_level,
    extract_link_id,
    get_iuu_subtypes,
    get_iuu_types,
    load_ids,
)
from model_metrics import (  # noqa: E402
    diff_overview,
    kde_rates,
    make_metric_accumulators,
    multiclass_metrics,
    multilabel_metrics,
    overview_summary,
)

# Schemas — used as JSON-schema payloads only, no behavior imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.models.iuu_classifications import IncidentClassification  # noqa: E402
from app.models.incident_data import ExtractedIncidentData  # noqa: E402
from app.models.overviews import IndustryOverviewExtract  # noqa: E402

logger = logging.getLogger(__name__)

SCOPE_LABELS = [
    "Single Incident",
    "Multiple Incidents",
    "Industry Overview",
    "Unrelated to IUU Fishing",
]


# Scope confusion-matrix uses this collapsed label set. We still ask the LM
# to predict the four-way label above (so single-vs-multi prompt branching
# stays correct) — the merge happens only when scoring.
_SCOPE_REMAP = {
    "Single Incident": "Incidents",
    "Multiple Incidents": "Incidents",
    "Industry Overview": "Industry Overview",
    "Unrelated": "Unrelated",
    "Unrelated to IUU Fishing": "Unrelated",
}


def _normalize_scope(label: str) -> str:
    return _SCOPE_REMAP.get(label, label)


# ── Prompts ────────────────────────────────────────────────────────────────

SCOPE_SYSTEM = f"""You are classifying news articles about IUU (Illegal, \
Unreported, Unregulated) fishing.

Return JSON with a single key "scope" whose value is exactly one of:
{json.dumps(SCOPE_LABELS)}.

Definitions:
- "Single Incident": one specific IUU+ incident with identified actor(s).
- "Multiple Incidents": two or more distinct IUU+ incidents with identified actors.
- "Industry Overview": discusses IUU+ topics but no specific identified incidents \
(policy, patrols, statistics, trends, broad enforcement).
- "Unrelated to IUU Fishing": article does not discuss IUU+ topics.

Reply with JSON only, no prose.
"""


def _incident_extract_system() -> str:
    extract_schema = ExtractedIncidentData.model_json_schema()
    classification_schema = IncidentClassification.model_json_schema()
    return (
        "You extract structured incident data and classify it under IUU "
        "categories in a single response.\n\n"
        "For a Single Incident article, return JSON of shape:\n"
        '{"extracted_information": <ExtractedIncidentData>, '
        '"incident_classification": <IncidentClassification>}\n\n'
        "For a Multiple Incidents article, return JSON of shape:\n"
        '{"incidents": [{"extracted_information": ..., '
        '"incident_classification": ...}, ...]}\n\n'
        "ExtractedIncidentData JSON schema:\n"
        f"{json.dumps(extract_schema)}\n\n"
        "IncidentClassification JSON schema:\n"
        f"{json.dumps(classification_schema)}\n\n"
        "Reply with JSON only, no prose. Omit optional fields you cannot "
        "fill from the article."
    )


def _overview_extract_system() -> str:
    schema = IndustryOverviewExtract.model_json_schema()
    return (
        "You extract structured industry overview information.\n\n"
        f"Return JSON matching this schema:\n{json.dumps(schema)}\n\n"
        "Reply with JSON only, no prose. Set lists to [] when nothing applies."
    )


def _user_payload(source: dict) -> str:
    return json.dumps(
        {
            "article_title": source.get("article_title"),
            "publisher": source.get("publisher"),
            "publication_date": source.get("publication_date"),
            "article_text": source.get("article_text"),
        },
        default=str,
    )


# ── LLM call ───────────────────────────────────────────────────────────────


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json\n"):
            text = text[5:]
    return text


def _call_lm_sync(lm: dspy.LM, system: str, user: str) -> str:
    """Synchronous chat completion via dspy.LM. Returns raw string content."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    # dspy.LM(...) returns a list of completion strings.
    out = lm(messages=messages, response_format={"type": "json_object"})
    if isinstance(out, list):
        if not out:
            raise RuntimeError("dspy.LM returned empty completion list")
        return out[0]
    if isinstance(out, str):
        return out
    raise RuntimeError(f"Unexpected dspy.LM return type: {type(out).__name__}")


async def _call_lm(lm: dspy.LM, system: str, user: str) -> str:
    return await asyncio.to_thread(_call_lm_sync, lm, system, user)


# ── Per-source extraction ─────────────────────────────────────────────────

# Top-level ExtractedIncidentData fields the LM often omits when the article
# doesn't mention them. The production schema marks them required; we fill in
# safe empty defaults here so the baseline doesn't fail validation on omissions
# that are semantically "I don't have this info".
_INCIDENT_DEFAULTS: dict[str, Any] = {
    "speciesInvolved": list,
    "productsInvolved": list,
    "description": str,
}

# IUUType -> allowed IUUSubType values. Mirrors the Literal definitions in
# app/models/iuu_classifications.py. We filter LM output against this set
# locally so near-miss strings ("Unauthorized transhipment", typos, etc.) and
# subtypes from the wrong category don't kill the whole classification.
_IUU_SUBTYPES_BY_TYPE: dict[str, set[str]] = {
    "Illegal Fishing": {
        "Exceeding catch quotas",
        "Keeping undersized fish",
        "Catching unauthorized or prohibited species",
        "Prohibited fishing gear",
        "Fishing in closed areas or closed seasons",
        "Invalid or no permit or license",
        "Obscuring vessel identity",
        "Unauthorized transshipment",
        "Falisfying Documents",
        "Obstructing inspectors",
        "Illegal bycatch practices",
    },
    "Unreported Catch": {
        "Un/underreported target catch weight or size",
        "Un/underreported discards/bycatch weight or size",
        "Misreported target catch species",
        "Misreported non-target catch species",
        "Misreported location or timing of fishing",
        "Misreported gear",
        "Unreported transshipment activities",
    },
    "Unregulated Fishing": {
        "Stateless vessel",
        "Fishing under flag not party to RFMO",
        "Fishing in unregulated areas or for unregulated stock",
    },
    "Seafood Fraud or Mislabeling": {
        "Species mislabeling or fraud",
        "Production information fraud",
    },
    "Forced Labor or Labor Abuse": {
        "Wage/Pay violations",
        "Abusive living conditions",
        "Abusive working conditions",
        "Inadequate crew size",
        "Physical or sexual violence",
        "Intimidation",
        "Families threatened",
        "Deception",
        "No work contracts",
        "Isolation",
        "Migrants threatened",
    },
    "Circumventing Prohibitions or Sanctions": {
        "Circumventing sanctions (individuals or corporations)",
        "Circumventing import prohibitions (countries or products)",
    },
    "Illegal Aquacultural Practices": {
        "Unapproved/non-native species",
        "Illegal sourcing of seed/broodstock",
        "Misrepresentation or falsification of farming operations",
        "Unlicensed/Unauthorized farm operations",
        "Stolen products",
    },
    "Other": {
        "Information not sufficient to determine specific IUU+ behavior",
        (
            "Crimes related to fishing or associated trade but distinct from "
            "IUU+ typology (e.g., murder of journalists investigating IUU+ "
            "fishing)"
        ),
        "Other",
    },
}


def _sanitize_incident_payload(payload: Any) -> dict:
    """Fill missing top-level required ExtractedIncidentData fields with empty
    defaults so the LM's omissions don't trip pydantic validation."""
    if not isinstance(payload, dict):
        return {field: factory() for field, factory in _INCIDENT_DEFAULTS.items()}
    for field, factory in _INCIDENT_DEFAULTS.items():
        if field not in payload:
            payload[field] = factory()
    return payload


def _sanitize_classification_payload(payload: Any) -> dict:
    """Drop classifications whose IUUType isn't recognized, and filter each
    classification's IUUSubType list to entries valid for its type. Mirrors
    the production schema's allowed values but is tolerant of LM near-misses
    (typos, miscategorized subtypes).
    """
    if not isinstance(payload, dict):
        return {"iuuClassifications": []}
    raw = payload.get("iuuClassifications")
    if not isinstance(raw, list):
        payload["iuuClassifications"] = []
        return payload

    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        iuu_type = item.get("IUUType")
        allowed = (
            _IUU_SUBTYPES_BY_TYPE.get(iuu_type) if isinstance(iuu_type, str) else None
        )
        if allowed is None:
            logger.warning(
                "Dropping classification with unrecognized IUUType: %r", iuu_type
            )
            continue
        subtypes = item.get("IUUSubType")
        if isinstance(subtypes, list):
            filtered = [s for s in subtypes if isinstance(s, str) and s in allowed]
            dropped = [s for s in subtypes if s not in filtered]
            if dropped:
                logger.warning(
                    "Filtered invalid subtypes for %s: %r", iuu_type, dropped
                )
            item["IUUSubType"] = filtered if filtered else None
        cleaned.append(item)
    payload["iuuClassifications"] = cleaned
    return payload


def _validate_incident_item(item: dict) -> dict:
    """Validate one {extracted_information, incident_classification} pair with
    baseline-side sanitization applied first. Returns the normalized dump."""
    ext_in = _sanitize_incident_payload(item.get("extracted_information") or {})
    cls_in = _sanitize_classification_payload(item.get("incident_classification") or {})
    ext = ExtractedIncidentData.model_validate(ext_in)
    cls_ = IncidentClassification.model_validate(cls_in)
    return {
        "extracted_information": ext.model_dump(mode="json"),
        "incident_classification": cls_.model_dump(mode="json"),
    }


async def extract_one(lm: dspy.LM, source: dict, model_name: str) -> dict:
    """Run scope + extraction for a single source. Returns the dump dict."""
    started = time.time()
    record: dict[str, Any] = {
        "source_id": str(source.get("_id") or source.get("id") or ""),
        "model": model_name,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "predicted_scope": None,
        "scope_raw_response": None,
        "extraction_raw_response": None,
        "extracted_information": None,
        "incident_classification": None,
        "incidents": None,
        "overview": None,
        "elapsed_seconds": None,
        "error": None,
    }

    try:
        user = _user_payload(source)

        scope_raw = await _call_lm(lm, SCOPE_SYSTEM, user)
        record["scope_raw_response"] = scope_raw
        scope_parsed = json.loads(_strip_code_fence(scope_raw))
        scope = scope_parsed.get("scope")
        if scope not in SCOPE_LABELS:
            raise ValueError(f"Bad scope label: {scope!r}")
        record["predicted_scope"] = scope

        if scope == "Unrelated to IUU Fishing":
            record["elapsed_seconds"] = round(time.time() - started, 2)
            return record

        if scope == "Industry Overview":
            raw = await _call_lm(lm, _overview_extract_system(), user)
            record["extraction_raw_response"] = raw
            parsed = json.loads(_strip_code_fence(raw))
            # Validate via Pydantic (best-effort; record raw on failure)
            validated = IndustryOverviewExtract.model_validate(parsed)
            record["overview"] = validated.model_dump(mode="json")
        else:
            raw = await _call_lm(lm, _incident_extract_system(), user)
            record["extraction_raw_response"] = raw
            parsed = json.loads(_strip_code_fence(raw))
            if scope == "Multiple Incidents":
                record["incidents"] = [
                    _validate_incident_item(item)
                    for item in parsed.get("incidents", [])
                ]
            else:  # Single Incident
                validated = _validate_incident_item(parsed)
                record["extracted_information"] = validated["extracted_information"]
                record["incident_classification"] = validated["incident_classification"]

    except Exception as exc:
        logger.warning("extract_one failed for %s: %s", record["source_id"], exc)
        record["error"] = f"{type(exc).__name__}: {exc}"

    record["elapsed_seconds"] = round(time.time() - started, 2)
    return record


# ── Diff prediction vs current state ──────────────────────────────────────


def _baseline_to_incident_state(record: dict) -> dict:
    """Wrap a baseline single-incident prediction in the same shape as a current
    incident document so diff_kde_* / get_iuu_types work unchanged."""
    return {
        "extracted_information": record.get("extracted_information") or {},
        "incident_classification": record.get("incident_classification")
        or {"iuuClassifications": []},
    }


def _baseline_to_overview_state(record: dict) -> dict:
    return {"extracted_information": record.get("overview") or {}}


async def fetch_current_state(api: ApiClient, source: dict) -> dict:
    """Collect the current DB state we need for diffing a single source.

    Async (does API GETs). Returned dict is JSON-serializable so it can be
    cached verbatim in ProgressDB and replayed without re-hitting the API.
    """
    ov_link = source.get("overview")
    overview_id: str | None = None
    current_overview: dict | None = None
    if ov_link:
        overview_id = extract_link_id(ov_link)
        if overview_id:
            if isinstance(ov_link, dict) and "extracted_information" in ov_link:
                current_overview = ov_link
            else:
                current_overview = await api.get_overview(overview_id)

    current_incidents: list[dict] = []
    for link in source.get("incidents") or []:
        incident_id = extract_link_id(link)
        if not incident_id:
            continue
        if isinstance(link, dict) and "extracted_information" in link:
            doc = link
        else:
            doc = await api.get_incident(incident_id)
        current_incidents.append({"id": incident_id, "doc": doc})

    return {
        "overview_id": overview_id,
        "current_overview": current_overview,
        "current_incidents": current_incidents,
    }


def apply_diff(
    record: dict,
    source: dict,
    current_state: dict,
    acc: dict,
    seen_incidents: set[str],
    seen_overviews: set[str],
) -> None:
    """Pure: update acc with diffs between baseline prediction and cached current state."""
    pred_scope = _normalize_scope(record.get("predicted_scope") or "<missing>")
    truth_scope = _normalize_scope(
        (source.get("article_scope") or {}).get("articleType") or "<none>"
    )
    acc["source_scope"][(pred_scope, truth_scope)] += 1
    acc["samples"]["scope"].append((pred_scope, truth_scope))
    acc["counts"]["sources_processed"] += 1

    if record.get("error"):
        return

    if record.get("overview") is not None:
        overview_id = current_state.get("overview_id")
        if overview_id and overview_id not in seen_overviews:
            seen_overviews.add(overview_id)
            curr_ov = current_state.get("current_overview")
            if curr_ov:
                diff_overview(_baseline_to_overview_state(record), curr_ov, acc)
            else:
                acc["overview"]["counts"]["overviews_skipped"] += 1
        return

    pred_incidents: list[dict] = []
    if record.get("incidents"):
        pred_incidents = record["incidents"]
    elif record.get("extracted_information") or record.get("incident_classification"):
        pred_incidents = [_baseline_to_incident_state(record)]

    if not pred_incidents:
        return

    current_incidents: list[dict] = []
    for inc in current_state.get("current_incidents") or []:
        incident_id = inc.get("id")
        if not incident_id or incident_id in seen_incidents:
            continue
        seen_incidents.add(incident_id)
        doc = inc.get("doc")
        if doc:
            current_incidents.append(doc)

    if not current_incidents:
        acc["counts"]["incidents_skipped"] += 1
        return

    if len(pred_incidents) == 1 and len(current_incidents) >= 1:
        pred = pred_incidents[0]
        curr = current_incidents[0]
        pred_types = get_iuu_types(pred.get("incident_classification"))
        truth_types = get_iuu_types(curr.get("incident_classification"))
        pred_subs = get_iuu_subtypes(pred.get("incident_classification"))
        truth_subs = get_iuu_subtypes(curr.get("incident_classification"))
        acc["samples"]["iuu_type"].append((pred_types, truth_types))
        acc["samples"]["iuu_subtype"].append((pred_subs, truth_subs))
        diff_kde_top_level(pred, curr, acc)
        diff_kde_leaf(pred, curr, acc)
        acc["counts"]["incidents_processed"] += 1
    else:
        agg_pred_types: set[str] = set()
        agg_pred_subs: set[str] = set()
        for p in pred_incidents:
            agg_pred_types |= get_iuu_types(p.get("incident_classification"))
            agg_pred_subs |= get_iuu_subtypes(p.get("incident_classification"))
        agg_truth_types: set[str] = set()
        agg_truth_subs: set[str] = set()
        for c in current_incidents:
            agg_truth_types |= get_iuu_types(c.get("incident_classification"))
            agg_truth_subs |= get_iuu_subtypes(c.get("incident_classification"))
        acc["samples"]["iuu_type"].append((agg_pred_types, agg_truth_types))
        acc["samples"]["iuu_subtype"].append((agg_pred_subs, agg_truth_subs))
        acc["counts"]["incidents_processed"] += 1
        # Skip KDE for multi-incident (alignment is fragile; documented limitation).


# ── Main runner ────────────────────────────────────────────────────────────


async def _extract_and_fetch(
    lm: dspy.LM,
    raw_id: str,
    source: dict,
    model_name: str,
    output_dir: Path,
    api: ApiClient,
    sem: asyncio.Semaphore,
) -> tuple[str, dict, dict]:
    """Run LM extraction (under semaphore) and fetch current state for diffing.

    Returns (raw_id, record, current_state). Does not mutate any accumulator;
    diff application happens serially in the caller.
    """
    async with sem:
        record = await extract_one(lm, source, model_name)

    out_file = output_dir / f"{record['source_id'] or raw_id}.json"
    out_file.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    current_state = await fetch_current_state(api, source)
    return raw_id, record, current_state


async def run(args: argparse.Namespace) -> None:
    ids = load_ids(args.ids_file)
    if args.limit:
        ids = ids[: args.limit]
    logger.info("Loaded %d source IDs (model=%s)", len(ids), args.model)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    progress_db_path: Path = args.progress_db or (args.output_dir / "_progress.db")
    db = ProgressDB(progress_db_path)
    if args.reset_progress:
        db.reset()
        logger.info("Progress DB reset: %s", progress_db_path)

    counts = db.counts_by_status()
    pending_count = sum(1 for i in ids if db.get_status(i) in (None, "failed"))
    logger.info(
        "Progress DB %s — success=%d failed=%d source_missing=%d "
        "pending_this_run=%d",
        progress_db_path,
        counts.get("success", 0),
        counts.get("failed", 0),
        counts.get("source_missing", 0),
        pending_count,
    )

    lm = dspy.LM(
        model=args.model,
        api_key=args.api_key,
        temperature=args.temperature,
    )

    api = ApiClient(args.base_url, args.auth_token)
    acc = make_metric_accumulators()
    seen_incidents: set[str] = set()
    seen_overviews: set[str] = set()
    sem = asyncio.Semaphore(args.concurrency)

    failures: list[dict] = []
    started = time.time()

    try:
        # Phase 1: replay cached successes / terminal skips in input order.
        pending: list[str] = []
        for raw_id in ids:
            status = db.get_status(raw_id)
            if status == "success":
                cached = db.load_payload(raw_id)
                if cached is not None:
                    apply_diff(
                        cached["record"],
                        cached["source"],
                        cached["current_state"],
                        acc,
                        seen_incidents,
                        seen_overviews,
                    )
                    continue
                logger.warning(
                    "Source %s marked success but payload missing; re-running",
                    raw_id,
                )
            if status == "source_missing":
                acc["counts"]["sources_missing"] += 1
                acc["skipped"].append({"id": raw_id, "reason": "source_not_found"})
                continue
            pending.append(raw_id)

        # Phase 2: fetch sources for pending IDs (sequential, cheap).
        pending_sources: list[tuple[str, dict]] = []
        for raw_id in pending:
            try:
                src = await api.get_source(raw_id)
            except Exception as exc:  # noqa: BLE001
                err = f"get_source: {type(exc).__name__}: {exc}"
                db.record_failure(raw_id, err)
                failures.append({"source_id": raw_id, "error": err})
                acc["skipped"].append({"id": raw_id, "reason": f"fetch_failed: {err}"})
                logger.warning("Source %s get_source failed: %s", raw_id, exc)
                continue
            if not src:
                db.record_terminal_skip(raw_id, "source_missing")
                acc["counts"]["sources_missing"] += 1
                acc["skipped"].append({"id": raw_id, "reason": "source_not_found"})
                continue
            pending_sources.append((raw_id, src))

        # Phase 3: concurrent LM extraction + current-state fetch.
        tasks = [
            _extract_and_fetch(lm, raw_id, src, args.model, args.output_dir, api, sem)
            for raw_id, src in pending_sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Phase 4: persist and apply diffs sequentially (preserves input order
        # for seen_* dedup determinism and serializes acc mutations).
        for (raw_id, src), result in zip(pending_sources, results):
            if isinstance(result, Exception):
                err = f"{type(result).__name__}: {result}"
                db.record_failure(raw_id, err)
                failures.append({"source_id": raw_id, "error": err})
                acc["skipped"].append(
                    {"id": raw_id, "reason": f"extract_failed: {err}"}
                )
                logger.warning("Source %s extract failed: %s", raw_id, result)
                continue
            _, record, current_state = result
            if record.get("error"):
                db.record_failure(raw_id, record["error"])
                failures.append({"source_id": raw_id, "error": record["error"]})
                continue
            db.record_success(
                raw_id,
                {
                    "source": src,
                    "record": record,
                    "current_state": current_state,
                },
            )
            apply_diff(record, src, current_state, acc, seen_incidents, seen_overviews)
    finally:
        await api.aclose()
        db.close()

    metrics = {
        "scope": multiclass_metrics(acc["samples"]["scope"]),
        "iuu_type": multilabel_metrics(acc["samples"]["iuu_type"]),
        "iuu_subtype": multilabel_metrics(acc["samples"]["iuu_subtype"]),
        "kde_top": kde_rates(acc["kde_top"]),
        "kde_leaf": kde_rates(acc["kde_leaf"]),
        "overview": overview_summary(acc),
    }

    elapsed = time.time() - started
    n_attempted = len(ids)
    n_succeeded = acc["counts"]["sources_processed"]

    print(f"\n=== Baseline run: model={args.model} ===")
    print(
        f"Attempted: {n_attempted}  succeeded: {n_succeeded}  "
        f"failures: {len(failures)}  elapsed: {elapsed:.1f}s"
    )
    _print_metrics(metrics)

    aggregate = {
        "model": args.model,
        "n_attempted": n_attempted,
        "n_succeeded": n_succeeded,
        "n_validation_failures": len(failures),
        "total_elapsed_seconds": round(elapsed, 2),
        "failures": failures,
        "counts": acc["counts"],
        "metrics": metrics,
    }
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(
        json.dumps(aggregate, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Wrote aggregate metrics to %s", args.metrics_output)
    logger.info("Per-source predictions in %s", args.output_dir)


def _print_metrics(metrics: dict) -> None:
    sm = metrics["scope"]
    print(
        f"\nScope: n={sm['n']} accuracy={sm['accuracy']} "
        f"macro_f1={sm['macro'].get('f1', 0)}"
    )
    for cls, m in sm["per_class"].items():
        print(
            f"  {cls:<30} P={m['precision']:>6} R={m['recall']:>6} "
            f"F1={m['f1']:>6} support={m['support']}"
        )

    for name, key in [("IUU type", "iuu_type"), ("IUU subtype", "iuu_subtype")]:
        bm = metrics[key]
        print(f"\n{name}: n={bm['n']} exact_match={bm.get('exact_match_rate')}")
        if bm.get("micro"):
            print(
                f"  micro: P={bm['micro']['precision']} R={bm['micro']['recall']} "
                f"F1={bm['micro']['f1']}"
            )
            print(
                f"  macro: P={bm['macro']['precision']} R={bm['macro']['recall']} "
                f"F1={bm['macro']['f1']}"
            )

    ov = metrics["overview"]
    if ov["counts"]["overviews_processed"]:
        print("\nIndustry Overview:")
        for field, m in ov["list_fields"].items():
            print(
                f"  {field:<12} P={m['precision']:>6} R={m['recall']:>6} "
                f"F1={m['f1']:>6}"
            )
        print(f"  summary: {dict(ov['summary'])}")


def _default_api_key(model: str) -> str | None:
    if model.startswith("anthropic/"):
        return os.environ.get("ANTHROPIC_API_KEY")
    return os.environ.get("OPENAI_API_KEY")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids-file", required=True, type=Path)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument("--auth-token", default=os.environ.get("AUTH_TOKEN"))
    parser.add_argument(
        "--model",
        default="openai/gpt-4o-mini",
        help="LiteLLM model string (e.g. openai/gpt-4o-mini, anthropic/claude-3-5-sonnet-latest)",
    )
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("scripts/baseline_runs"),
        help="Per-source prediction dumps land here as {source_id}.json",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=Path("scripts/baseline_metrics.json"),
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument(
        "--progress-db",
        type=Path,
        default=None,
        help=(
            "SQLite DB used to cache per-source LM extractions so a crashed run "
            "can resume without re-spending tokens. "
            "Defaults to {output-dir}/_progress.db."
        ),
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Wipe the progress DB before running.",
    )
    parser.add_argument(
        "--list-failed",
        action="store_true",
        help="Print source IDs with status='failed' from the progress DB and exit.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.list_failed:
        progress_db_path = args.progress_db or (args.output_dir / "_progress.db")
        db = ProgressDB(progress_db_path)
        try:
            any_rows = False
            for sid, err in db.iter_failed():
                print(f"{sid}\t{err}")
                any_rows = True
            if not any_rows:
                logger.info("No failed sources in %s", progress_db_path)
        finally:
            db.close()
        return

    if args.api_key is None:
        args.api_key = _default_api_key(args.model)
        if not args.api_key:
            logger.warning(
                "No API key supplied and neither OPENAI_API_KEY nor "
                "ANTHROPIC_API_KEY is set; LM calls will likely fail."
            )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
