"""Compare AI-extracted (v1) vs current human-reviewed state for a list of Sources.

Talks only to the public HTTP API:
    GET /api/sources/{id}                    -> current source
    GET /api/incidents/{id}                  -> current incident
    GET /api/logs/{id}/version/1             -> reconstructed v1 state

Outputs aggregate stats on:
  A. Source scope classification transitions
  B. IUU type transitions (added / removed / unchanged)
  C. IUU subtype transitions
  D. KDE field changes (top-level + leaf-level): correct / correct_empty /
     missing / spurious / mismatch  (IE slot-filling buckets)

Usage:
    python scripts/review_analysis.py \
        --ids-file source_ids.json \
        --base-url http://localhost:8000 \
        --auth-token "$AUTH_TOKEN" \
        --output scripts/review_analysis.json

The auth token is the same NextAuth JWT used by webScraper/upload_scraped_data.py
(/api/logs requires admin auth). May also be supplied via AUTH_TOKEN env var.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parent))

from _review_lib import (  # noqa: E402
    ApiClient,
    diff_iuu_subtypes,
    diff_iuu_types,
    diff_kde_leaf,
    diff_kde_top_level,
    diff_source_scope,
    extract_link_id,
    load_ids,
    make_accumulators,
)

logger = logging.getLogger(__name__)


async def run(
    ids_file: Path, output: Path, base_url: str, auth_token: str | None
) -> None:
    ids = load_ids(ids_file)
    logger.info("Loaded %d source IDs", len(ids))

    acc = make_accumulators()
    seen_incidents: set[str] = set()
    api = ApiClient(base_url, auth_token)
    try:
        for raw_id in ids:
            source = await api.get_source(raw_id)
            if not source:
                acc["counts"]["sources_missing"] += 1
                acc["skipped"].append({"id": raw_id, "reason": "source_not_found"})
                continue

            v1_state = await api.get_v1_state(raw_id)
            diff_source_scope(v1_state, source, acc)
            acc["counts"]["sources_processed"] += 1

            for link in source.get("incidents") or []:
                incident_id = extract_link_id(link)
                if not incident_id or incident_id in seen_incidents:
                    continue
                seen_incidents.add(incident_id)

                # If the source response already inlined the full incident, use it
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

                diff_iuu_types(inc_v1, curr, acc)
                diff_iuu_subtypes(inc_v1, curr, acc)
                diff_kde_top_level(inc_v1, curr, acc)
                diff_kde_leaf(inc_v1, curr, acc)
                acc["counts"]["incidents_processed"] += 1
    finally:
        await api.aclose()

    print_summary(acc)
    write_json(acc, output)
    logger.info("Wrote detailed JSON to %s", output)


def print_summary(acc: dict) -> None:
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

    print("\n=== A. Source scope transitions ===")
    for (orig, curr), count in sorted(acc["source_scope"].items(), key=lambda x: -x[1]):
        print(f"  {count:>4}  {orig} -> {curr}")

    print("\n=== B. IUU type ===")
    print(f"  unchanged: {acc['iuu_type_unchanged']}")
    print("  added by reviewer:")
    for k, v in acc["iuu_type_added"].most_common():
        print(f"    {v:>4}  {k}")
    print("  removed by reviewer:")
    for k, v in acc["iuu_type_removed"].most_common():
        print(f"    {v:>4}  {k}")

    print("\n=== C. IUU subtype ===")
    print(f"  unchanged: {acc['iuu_subtype_unchanged']}")
    print("  added by reviewer:")
    for k, v in acc["iuu_subtype_added"].most_common():
        print(f"    {v:>4}  {k}")
    print("  removed by reviewer:")
    for k, v in acc["iuu_subtype_removed"].most_common():
        print(f"    {v:>4}  {k}")

    header = (
        f"  {'field':<32} {'correct':>8} {'tn':>6} "
        f"{'missing':>8} {'spurious':>9} {'mismatch':>9}"
    )
    leaf_header = (
        f"  {'field':<60} {'correct':>8} {'tn':>6} "
        f"{'missing':>8} {'spurious':>9} {'mismatch':>9}"
    )

    def _row(field: str, b: dict, width: int) -> str:
        return (
            f"  {field:<{width}} {b.get('correct', 0):>8} "
            f"{b.get('correct_empty', 0):>6} {b.get('missing', 0):>8} "
            f"{b.get('spurious', 0):>9} {b.get('mismatch', 0):>9}"
        )

    print("\n=== D1. KDE top-level (per-incident) ===")
    print(header)
    for field in sorted(acc["kde_top"].keys()):
        print(_row(field, acc["kde_top"][field], 32))

    print("\n=== D2. KDE leaf-level (top 30 by error count) ===")
    leaf_items = []
    for field, b in acc["kde_leaf"].items():
        errors = b.get("missing", 0) + b.get("spurious", 0) + b.get("mismatch", 0)
        leaf_items.append((errors, field, b))
    leaf_items.sort(reverse=True)
    print(leaf_header)
    for _, field, b in leaf_items[:30]:
        print(_row(field, b, 60))
    print(f"  (full per-leaf breakdown of {len(leaf_items)} fields in JSON output)")


def write_json(acc: dict, path: Path) -> None:
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
        default=Path("scripts/review_analysis.json"),
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
