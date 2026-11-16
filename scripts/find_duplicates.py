"""Run duplicate detection and export candidate pairs to CSV for analysis.

Each row is one candidate pair with the vector score, every per-KDE score in
its own column, the combined score and coverage, plus the raw KDE values of
both incidents so pairs can be hand-labelled to tune weights/thresholds in
``app/dedup/kde_compare.py``.

Usage:
    # Scan every incident, then export all pending candidates:
    python scripts/find_duplicates.py --scan --csv duplicates.csv

    # Export only (no rescan), include pairs that share a source:
    python scripts/find_duplicates.py --csv duplicates.csv --include-shared-source

    # Looser neighbour threshold to see what sits just below the cutoff:
    python scripts/find_duplicates.py --scan --min-vector 0.7 --csv loose.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

KDE_COLUMNS = [
    "identifiers",
    "vessel_name",
    "vessel_flag",
    "event_date",
    "location",
    "country",
    "species",
    "iuu_types",
]


def _kde_summary(kdes: dict | None) -> dict:
    if not kdes:
        return {}
    return {
        "vessel_name": kdes.get("vessel_name"),
        "vessel_flag": kdes.get("vessel_flag"),
        "event_date": kdes.get("event_date"),
        "locations": " | ".join(kdes.get("locations") or []),
        "country": kdes.get("country"),
        "species": " | ".join(
            s.get("asfis") or s.get("scientific") or s.get("common") or ""
            for s in kdes.get("species") or []
        ),
        "iuu_types": " | ".join(kdes.get("iuu_types") or []),
    }


async def run(args: argparse.Namespace) -> None:
    from pymongo import DESCENDING

    from app.database import init_db
    from app.models.duplicates import DuplicateCandidate
    from app.service.dedup_service import DedupService

    await init_db()

    if args.scan:
        result = await DedupService.scan_all(k=args.k, min_vector=args.min_vector)
        logger.info("Scan complete: %s", result)

    if not args.csv:
        return

    query: dict = {"combined_score": {"$gte": args.min_score}}
    if args.status != "any":
        query["status"] = args.status
    if not args.include_shared_source:
        query["shares_source"] = False

    candidates = (
        await DuplicateCandidate.find(query)
        .sort([("combined_score", DESCENDING)])
        .to_list()
    )

    fieldnames = (
        ["candidate_id", "status", "combined_score", "coverage", "vector_score"]
        + [f"score_{c}" for c in KDE_COLUMNS]
        + ["shares_source", "incident_a_id", "incident_b_id"]
        + [f"a_{k}" for k in _kde_summary({"x": 1}).keys()]
        + [f"b_{k}" for k in _kde_summary({"x": 1}).keys()]
        + ["a_description", "b_description"]
    )

    with open(args.csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in candidates:
            detail = await DedupService.candidate_detail(candidate)
            a, b = detail["incident_a"] or {}, detail["incident_b"] or {}
            row = {
                "candidate_id": str(candidate.id),
                "status": candidate.status,
                "combined_score": candidate.combined_score,
                "coverage": candidate.coverage,
                "vector_score": candidate.vector_score,
                "shares_source": candidate.shares_source,
                "incident_a_id": str(candidate.incident_a_id),
                "incident_b_id": str(candidate.incident_b_id),
                "a_description": a.get("description"),
                "b_description": b.get("description"),
            }
            for column in KDE_COLUMNS:
                row[f"score_{column}"] = candidate.kde_scores.get(column)
            for key, value in _kde_summary(a.get("kdes")).items():
                row[f"a_{key}"] = value
            for key, value in _kde_summary(b.get("kdes")).items():
                row[f"b_{key}"] = value
            writer.writerow(row)

    logger.info("Wrote %d candidate pairs to %s", len(candidates), args.csv)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="Rescan all incidents.")
    parser.add_argument("--k", type=int, default=10, help="Neighbours per incident.")
    parser.add_argument(
        "--min-vector",
        type=float,
        default=0.80,
        help="Minimum cosine similarity for a neighbour to become a candidate.",
    )
    parser.add_argument("--csv", help="Write candidates to this CSV path.")
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument(
        "--status",
        default="pending",
        choices=["any", "pending", "duplicate", "not_duplicate", "merged"],
    )
    parser.add_argument("--include-shared-source", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
