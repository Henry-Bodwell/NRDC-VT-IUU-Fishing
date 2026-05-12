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
            text = text[: -3]
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

async def extract_one(
    lm: dspy.LM, source: dict, model_name: str
) -> dict:
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
                incidents_out: list[dict] = []
                for item in parsed.get("incidents", []):
                    ext = ExtractedIncidentData.model_validate(
                        item.get("extracted_information") or {}
                    )
                    cls_ = IncidentClassification.model_validate(
                        item.get("incident_classification") or {}
                    )
                    incidents_out.append(
                        {
                            "extracted_information": ext.model_dump(mode="json"),
                            "incident_classification": cls_.model_dump(mode="json"),
                        }
                    )
                record["incidents"] = incidents_out
            else:  # Single Incident
                ext = ExtractedIncidentData.model_validate(
                    parsed.get("extracted_information") or {}
                )
                cls_ = IncidentClassification.model_validate(
                    parsed.get("incident_classification") or {}
                )
                record["extracted_information"] = ext.model_dump(mode="json")
                record["incident_classification"] = cls_.model_dump(mode="json")

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
        "incident_classification": record.get("incident_classification") or {
            "iuuClassifications": []
        },
    }


def _baseline_to_overview_state(record: dict) -> dict:
    return {"extracted_information": record.get("overview") or {}}


async def diff_against_current(
    record: dict,
    source: dict,
    api: ApiClient,
    acc: dict,
    seen_incidents: set[str],
    seen_overviews: set[str],
) -> None:
    """Update acc with diffs between baseline prediction (record) and current state."""
    # Scope
    pred_scope = record.get("predicted_scope") or "<missing>"
    truth_scope = (
        (source.get("article_scope") or {}).get("articleType") or "<none>"
    )
    acc["source_scope"][(pred_scope, truth_scope)] += 1
    acc["samples"]["scope"].append((pred_scope, truth_scope))
    acc["counts"]["sources_processed"] += 1

    if record.get("error"):
        return

    # Overview
    if record.get("overview") is not None:
        ov_link = source.get("overview")
        overview_id = extract_link_id(ov_link)
        if overview_id and overview_id not in seen_overviews:
            seen_overviews.add(overview_id)
            curr_ov = (
                ov_link
                if isinstance(ov_link, dict)
                and "extracted_information" in ov_link
                else await api.get_overview(overview_id)
            )
            if curr_ov:
                diff_overview(_baseline_to_overview_state(record), curr_ov, acc)
            else:
                acc["overview"]["counts"]["overviews_skipped"] += 1
        return

    # Incident(s)
    pred_incidents: list[dict] = []
    if record.get("incidents"):
        pred_incidents = record["incidents"]
    elif record.get("extracted_information") or record.get("incident_classification"):
        pred_incidents = [_baseline_to_incident_state(record)]

    if not pred_incidents:
        return

    # Align to current incidents: Single -> first; Multiple -> aggregate set-level only.
    current_incidents: list[dict] = []
    for link in source.get("incidents") or []:
        incident_id = extract_link_id(link)
        if not incident_id or incident_id in seen_incidents:
            continue
        seen_incidents.add(incident_id)
        if isinstance(link, dict) and "extracted_information" in link:
            current_incidents.append(link)
        else:
            curr = await api.get_incident(incident_id)
            if curr:
                current_incidents.append(curr)

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
        # Multiple incidents — aggregate set-level only (no per-incident alignment).
        pred_types: set[str] = set()
        pred_subs: set[str] = set()
        for p in pred_incidents:
            pred_types |= get_iuu_types(p.get("incident_classification"))
            pred_subs |= get_iuu_subtypes(p.get("incident_classification"))
        truth_types: set[str] = set()
        truth_subs: set[str] = set()
        for c in current_incidents:
            truth_types |= get_iuu_types(c.get("incident_classification"))
            truth_subs |= get_iuu_subtypes(c.get("incident_classification"))
        acc["samples"]["iuu_type"].append((pred_types, truth_types))
        acc["samples"]["iuu_subtype"].append((pred_subs, truth_subs))
        acc["counts"]["incidents_processed"] += 1
        # Skip KDE for multi-incident (alignment is fragile; documented limitation).


# ── Main runner ────────────────────────────────────────────────────────────

async def _process_source(
    lm: dspy.LM,
    source: dict,
    model_name: str,
    output_dir: Path,
    api: ApiClient,
    acc: dict,
    seen_incidents: set[str],
    seen_overviews: set[str],
    sem: asyncio.Semaphore,
) -> dict:
    async with sem:
        record = await extract_one(lm, source, model_name)

    out_file = output_dir / f"{record['source_id']}.json"
    out_file.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    await diff_against_current(record, source, api, acc, seen_incidents, seen_overviews)
    return record


async def run(args: argparse.Namespace) -> None:
    ids = load_ids(args.ids_file)
    if args.limit:
        ids = ids[: args.limit]
    logger.info("Loaded %d source IDs (model=%s)", len(ids), args.model)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    lm = dspy.LM(
        model=args.model,
        api_key=args.api_key,
        max_tokens=args.max_tokens,
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
        # Pre-fetch all sources sequentially (cheap), then run extractions concurrently
        sources: list[tuple[str, dict | None]] = []
        for raw_id in ids:
            sources.append((raw_id, await api.get_source(raw_id)))

        tasks = []
        for raw_id, src in sources:
            if not src:
                acc["counts"]["sources_missing"] += 1
                acc["skipped"].append({"id": raw_id, "reason": "source_not_found"})
                continue
            tasks.append(
                _process_source(
                    lm,
                    src,
                    args.model,
                    args.output_dir,
                    api,
                    acc,
                    seen_incidents,
                    seen_overviews,
                    sem,
                )
            )
        records = await asyncio.gather(*tasks, return_exceptions=True)
        for r in records:
            if isinstance(r, Exception):
                failures.append({"error": f"{type(r).__name__}: {r}"})
            elif isinstance(r, dict) and r.get("error"):
                failures.append({"source_id": r.get("source_id"), "error": r["error"]})
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

    elapsed = time.time() - started
    n_attempted = len(ids)
    n_succeeded = acc["counts"]["sources_processed"]

    print(f"\n=== Baseline run: model={args.model} ===")
    print(f"Attempted: {n_attempted}  succeeded: {n_succeeded}  "
          f"failures: {len(failures)}  elapsed: {elapsed:.1f}s")
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
    print(f"\nScope: n={sm['n']} accuracy={sm['accuracy']} "
          f"macro_f1={sm['macro'].get('f1', 0)}")
    for cls, m in sm["per_class"].items():
        print(f"  {cls:<30} P={m['precision']:>6} R={m['recall']:>6} "
              f"F1={m['f1']:>6} support={m['support']}")

    for name, key in [("IUU type", "iuu_type"), ("IUU subtype", "iuu_subtype")]:
        bm = metrics[key]
        print(f"\n{name}: n={bm['n']} exact_match={bm.get('exact_match_rate')}")
        if bm.get("micro"):
            print(f"  micro: P={bm['micro']['precision']} R={bm['micro']['recall']} "
                  f"F1={bm['micro']['f1']}")
            print(f"  macro: P={bm['macro']['precision']} R={bm['macro']['recall']} "
                  f"F1={bm['macro']['f1']}")

    ov = metrics["overview"]
    if ov["counts"]["overviews_processed"]:
        print("\nIndustry Overview:")
        for field, m in ov["list_fields"].items():
            print(f"  {field:<12} P={m['precision']:>6} R={m['recall']:>6} "
                  f"F1={m['f1']:>6}")
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
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
