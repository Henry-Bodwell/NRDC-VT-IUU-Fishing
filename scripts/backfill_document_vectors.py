"""Backfill document-level vectors for existing incidents and industry overviews.

Populates the Qdrant ``document_vectors`` collection used for cross-document
similarity (duplicate detection, clustering). Resumable and idempotent:

    - Documents whose ``embedding_text_hash`` matches their current embedded
      text are skipped (unless --force), so re-running only picks up new or
      edited documents.
    - Point ids are derived from (doc_type, doc_id), so re-indexing overwrites.

Usage:
    python scripts/backfill_document_vectors.py
    python scripts/backfill_document_vectors.py --only incidents --force
    python scripts/backfill_document_vectors.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# text-embedding-3-small list price (USD per 1M tokens) -- for the cost estimate.
_EMBED_PRICE_PER_1M = 0.02


async def _select(model_cls, text_fn, force: bool):
    """Return (documents to index, skipped count, total tokens)."""
    from app.dspy_files.config import count_tokens

    selected, skipped, tokens = [], 0, 0
    async for doc in model_cls.find_all():
        text, text_hash = text_fn(doc)
        if not text:
            skipped += 1
            continue
        if not force and doc.embedding_text_hash == text_hash:
            skipped += 1
            continue
        selected.append(doc)
        tokens += count_tokens(text)
    return selected, skipped, tokens


async def run(args: argparse.Namespace) -> None:
    from app.database import init_db
    from app.models.incidents import IncidentReport, IndustryOverview
    from app.rag.document_index import index_incidents, index_overview
    from app.rag.document_text import incident_embedding_text, overview_embedding_text
    from app.rag.vector_store import get_document_store

    await init_db()
    await get_document_store().ensure_collection()

    incidents, overviews = [], []
    total_tokens = 0
    if args.only in ("all", "incidents"):
        incidents, skipped, tokens = await _select(
            IncidentReport, incident_embedding_text, args.force
        )
        total_tokens += tokens
        logger.info("Incidents: %d to index, %d skipped", len(incidents), skipped)
    if args.only in ("all", "overviews"):
        overviews, skipped, tokens = await _select(
            IndustryOverview, overview_embedding_text, args.force
        )
        total_tokens += tokens
        logger.info("Overviews: %d to index, %d skipped", len(overviews), skipped)

    logger.info(
        "~%d tokens, estimated embedding cost ~$%.4f",
        total_tokens,
        total_tokens / 1_000_000 * _EMBED_PRICE_PER_1M,
    )
    if args.dry_run:
        logger.info("Dry run -- no embeddings written.")
        return

    indexed = 0
    for start in range(0, len(incidents), args.batch_size):
        batch = incidents[start : start + args.batch_size]
        indexed += await index_incidents(batch, force=True)
        logger.info("Incidents indexed: %d/%d", indexed, len(incidents))

    overview_count = 0
    for overview in overviews:
        overview_count += int(await index_overview(overview, force=True))
    logger.info(
        "Backfill complete: %d incidents, %d overviews indexed.",
        indexed,
        overview_count,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", choices=["all", "incidents", "overviews"], default="all"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed even if the stored text hash is current.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report selection + estimated cost without writing embeddings.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Incidents embedded per embedding request.",
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
