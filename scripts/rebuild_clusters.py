"""Re-cluster all indexed incidents and overviews, then summarise changed clusters.

Requires document vectors (run scripts/backfill_document_vectors.py first).

Usage:
    # Preview what HDBSCAN finds without writing anything (no LLM calls):
    python scripts/rebuild_clusters.py --dry-run

    # Rebuild and summarise new/changed clusters:
    python scripts/rebuild_clusters.py

    # Tighter clusters, no summaries:
    python scripts/rebuild_clusters.py --min-cluster-size 5 --threshold 0.8 --no-summarize
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


async def run(args: argparse.Namespace) -> None:
    from app.database import init_db
    from app.service.cluster_service import ClusterService

    await init_db()
    stats = await ClusterService.rebuild(
        min_cluster_size=args.min_cluster_size,
        membership_threshold=args.threshold,
        summarize=not args.no_summarize,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        await _print_proposals(stats.pop("proposals", []), args.show)
    logger.info("Rebuild result: %s", json.dumps(stats))


async def _print_proposals(proposals: list[dict], show: int) -> None:
    """Print each proposed cluster with a few member descriptions."""
    from beanie import PydanticObjectId

    from app.models.incidents import IncidentReport, IndustryOverview

    for n, proposal in enumerate(proposals, 1):
        members = proposal["members"]
        print(
            f"\n== Cluster {n}: {len(members)} members "
            f"({proposal['core_size']} core) =="
        )
        for key in members[:show]:
            doc_type, doc_id = key.split(":", 1)
            if doc_type == "incident":
                doc = await IncidentReport.get(PydanticObjectId(doc_id))
                label = doc.extracted_information.description if doc else "?"
            else:
                doc = await IndustryOverview.get(PydanticObjectId(doc_id))
                label = doc.extracted_information.summary if doc else "?"
            print(f"  [{doc_type}] {(label or '')[:140]}")
        if len(members) > show:
            print(f"  ... and {len(members) - show} more")


def main() -> None:
    from app.clustering.engine import (
        DEFAULT_MEMBERSHIP_THRESHOLD,
        DEFAULT_MIN_CLUSTER_SIZE,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-cluster-size", type=int, default=DEFAULT_MIN_CLUSTER_SIZE
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_MEMBERSHIP_THRESHOLD,
        help="Centroid cosine similarity for overlapping (soft) membership.",
    )
    parser.add_argument("--no-summarize", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--show", type=int, default=5, help="Members printed per cluster (dry run)."
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
