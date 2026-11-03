"""Backfill chunk embeddings for existing Source documents into the vector store.

This is a resumable, idempotent maintenance job -- NOT a schema migration. The
new Source bookkeeping fields (chunk_count / indexed_at / embedding_model) are
nullable, so existing documents are already valid; this job only populates the
Qdrant vector store so the deferred cross-document search / incident
de-duplication work has embeddings to query.

Safe to run, stop, and re-run:
    - Resumable: skips sources already indexed with the current embedding model
      (unless --force).
    - Idempotent: VectorStore.index_source deletes a source's existing points
      (by article_hash) before upserting, so chunks never duplicate.

Usage:
    # Only documents large enough to take the live RAG path (matches the gate):
    python scripts/backfill_chunks.py --large-only

    # Whole corpus (needed for corpus-wide cross-document search):
    python scripts/backfill_chunks.py --all

    # Preview selection + estimated embedding cost without writing anything:
    python scripts/backfill_chunks.py --all --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# text-embedding-3-small list price (USD per 1M tokens) -- for the cost estimate.
_EMBED_PRICE_PER_1M = 0.02

# Token count above which --large-only considers a source worth backfilling.
# The pipeline itself no longer gates on size (every source is indexed); this is
# purely a convenience filter for prioritising a large backlog.
_LARGE_SOURCE_TOKENS = 6000


async def _select_sources(large_only: bool):
    """Yield (source, token_count) pairs eligible for backfill."""
    from app.models.sources import Source
    from app.dspy_files.config import count_tokens

    async for source in Source.find_all():
        if not source.article_text:
            continue
        tokens = count_tokens(source.article_text)
        if large_only and tokens < _LARGE_SOURCE_TOKENS:
            continue
        yield source, tokens


async def _index_one(store, source, semaphore) -> int:
    """Chunk + index a single source with bounded concurrency and a retry."""
    from app.dspy_files.config import EMBEDDING_MODEL
    from app.models.sources import Source
    from app.rag.chunking import chunk_text

    async with semaphore:
        chunks = chunk_text(source.article_text)
        for attempt in range(3):
            try:
                await store.index_source(source, chunks)
                break
            except Exception as e:
                if attempt == 2:
                    raise
                wait = 2**attempt
                logger.warning(
                    "Index failed for %s (attempt %d): %s; retrying in %ds",
                    source.article_hash,
                    attempt + 1,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)

    await Source.get_pymongo_collection().update_one(
        {"_id": source.id},
        {
            "$set": {
                "chunk_count": len(chunks),
                "indexed_at": datetime.utcnow(),
                "embedding_model": EMBEDDING_MODEL,
            }
        },
    )
    return len(chunks)


async def run(args: argparse.Namespace) -> None:
    from app.database import init_db
    from app.dspy_files.config import EMBEDDING_MODEL
    from app.rag.vector_store import get_vector_store

    await init_db()
    store = get_vector_store()
    await store.ensure_collection()

    # Selection pass (also drives the cost estimate).
    selected = []
    skipped = 0
    total_tokens = 0
    async for source, tokens in _select_sources(args.large_only):
        already = (
            source.indexed_at is not None and source.embedding_model == EMBEDDING_MODEL
        )
        if already and not args.force:
            skipped += 1
            continue
        selected.append(source)
        total_tokens += tokens

    est_cost = total_tokens / 1_000_000 * _EMBED_PRICE_PER_1M
    logger.info(
        "Selected %d source(s) (%d skipped as already-indexed); "
        "~%d tokens, estimated embedding cost ~$%.4f with %s",
        len(selected),
        skipped,
        total_tokens,
        est_cost,
        EMBEDDING_MODEL,
    )

    if args.dry_run:
        logger.info("Dry run -- no embeddings written.")
        return

    semaphore = asyncio.Semaphore(args.concurrency)
    tasks = [_index_one(store, source, semaphore) for source in selected]

    indexed_sources = 0
    indexed_chunks = 0
    for coro in asyncio.as_completed(tasks):
        try:
            n = await coro
            indexed_sources += 1
            indexed_chunks += n
            if indexed_sources % 25 == 0:
                logger.info(
                    "Progress: %d/%d sources indexed", indexed_sources, len(selected)
                )
        except Exception as e:
            logger.error("Failed to index a source: %s", e)

    logger.info(
        "Backfill complete: %d sources, %d chunks indexed.",
        indexed_sources,
        indexed_chunks,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--all",
        dest="large_only",
        action="store_false",
        help="Index every source, matching the pipeline's behaviour (default).",
    )
    scope.add_argument(
        "--large-only",
        dest="large_only",
        action="store_true",
        help=(
            f"Only index sources of at least {_LARGE_SOURCE_TOKENS} tokens, "
            f"for prioritising a large backlog."
        ),
    )
    parser.set_defaults(large_only=False)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-index sources even if already indexed with the current model.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report selection + estimated cost without writing embeddings.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Maximum number of sources embedded concurrently.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
