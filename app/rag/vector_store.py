"""Persistent vector store for source-document chunks (Qdrant-backed).

Wraps an async Qdrant client plus a DSPy embedder behind a small interface so
the rest of the pipeline never touches Qdrant types directly. The store is the
source of truth for chunk text + vectors; MongoDB only keeps lightweight
bookkeeping (chunk_count / indexed_at) on the Source.

Chunks are keyed on ``article_hash``, not the Mongo ``_id``: sources are
indexed during ingestion before they are inserted, and the hash is the one key
that is stable from then on. Indexing is idempotent per article_hash: point ids
are deterministic, so re-ingesting a document overwrites its existing points and
only the stale tail (if it now has fewer chunks) is removed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections import OrderedDict
from typing import Any

from app.rag.chunking import Chunk

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "source_chunks"
EMBEDDING_DIM = 1536

# Upper bound on cached query vectors (see VectorStore._embed_query).
_QUERY_CACHE_MAX = 128

# Stable namespace so point ids are deterministic across processes/runs.
_POINT_NAMESPACE = uuid.UUID("6f6b1b3e-2c2a-4f1a-9b9a-1d5c7e2a4f10")


def point_id(article_hash: str, chunk_index: int) -> str:
    """Deterministic Qdrant point id for a chunk of a given document."""
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{article_hash}:{chunk_index}"))


def source_scope_key(source: Any) -> str:
    """Stable retrieval-scoping key for a source: its ``article_hash``.

    The hash exists before the source is inserted and never changes after, so
    chunks indexed during ingestion stay reachable for retrieval and deletion.
    """
    return getattr(source, "article_hash", "")


def chunk_to_payload(source_id: Any, article_hash: str, chunk: Chunk) -> dict:
    """Build the Qdrant payload stored alongside a chunk's vector.

    ``source_id`` is informational only (it is ``None`` for sources indexed
    before insert); scoping and deletion filter on ``article_hash``.
    """
    return {
        "source_id": str(source_id) if source_id is not None else None,
        "article_hash": article_hash,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "start_char": chunk.start_char,
        "end_char": chunk.end_char,
    }


def payload_to_chunk(payload: dict, score: float | None = None) -> Chunk:
    """Reconstruct a :class:`Chunk` from a stored Qdrant payload.

    ``score`` is supplied by :meth:`VectorStore.retrieve` for query results and
    left ``None`` everywhere else.
    """
    return Chunk(
        text=payload.get("text", ""),
        chunk_index=payload.get("chunk_index", 0),
        start_char=payload.get("start_char", 0),
        end_char=payload.get("end_char", 0),
        score=score,
    )


class VectorStore:
    """Thin async wrapper around Qdrant + a DSPy embedder."""

    def __init__(self, client, embedder, collection: str = DEFAULT_COLLECTION):
        self.client = client
        self.embedder = embedder
        self.collection = collection
        # Query-vector cache. The 13 category queries are static and now run on
        # every document, so embedding them once per process instead of once per
        # extraction removes the bulk of the embedding calls. Bounded because
        # multi-incident queries are document-specific and would otherwise grow
        # without limit.
        self._query_vectors: OrderedDict[str, list[float]] = OrderedDict()
        # Set once ensure_collection() succeeds. Startup may run before Qdrant
        # is reachable, so indexing retries until the collection is confirmed.
        self._collection_ready = False

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts off the event loop (the DSPy embedder is synchronous)."""
        vectors = await asyncio.to_thread(self.embedder, texts)
        return [list(map(float, v)) for v in vectors]

    async def _embed_query(self, query: str) -> list[float]:
        """Embed a query string, reusing the cached vector when seen before."""
        cached = self._query_vectors.get(query)
        if cached is not None:
            self._query_vectors.move_to_end(query)
            return cached

        vector = (await self._embed([query]))[0]
        self._query_vectors[query] = vector
        if len(self._query_vectors) > _QUERY_CACHE_MAX:
            self._query_vectors.popitem(last=False)
        return vector

    async def ensure_collection(self) -> None:
        """Create the chunk collection and its payload indexes if missing."""
        from qdrant_client import models

        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIM, distance=models.Distance.COSINE
                ),
            )

        # Scoped retrieval, re-indexing and deletion all filter on article_hash;
        # without a payload index those are unindexed scans. Qdrant treats
        # re-creating an existing index as a no-op, so this is safe to run on
        # every startup.
        for field in ("article_hash",):
            try:
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception as e:
                logger.debug(f"Payload index for '{field}' not created: {e}")

        self._collection_ready = True

    async def _ensure_ready(self) -> None:
        """Create the collection on first use if startup could not."""
        if not self._collection_ready:
            await self.ensure_collection()

    async def index_source(self, source: Any, chunks: list[Chunk]) -> int:
        """Embed and upsert a source's chunks; returns the number indexed.

        Idempotent: point ids are deterministic, so the upsert overwrites any
        existing points for the source's article_hash. Only the stale tail
        (chunk indices past the new count) is deleted, and only after the upsert
        succeeds, so a failed re-index never leaves the source with no chunks.
        """
        if not chunks:
            return 0

        from qdrant_client import models

        await self._ensure_ready()

        article_hash = source.article_hash
        source_id = getattr(source, "id", None)

        vectors = await self._embed([c.text for c in chunks])

        points = [
            models.PointStruct(
                id=point_id(article_hash, chunk.chunk_index),
                vector=vectors[i],
                payload=chunk_to_payload(source_id, article_hash, chunk),
            )
            for i, chunk in enumerate(chunks)
        ]
        await self.client.upsert(collection_name=self.collection, points=points)

        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="article_hash",
                            match=models.MatchValue(value=article_hash),
                        ),
                        models.FieldCondition(
                            key="chunk_index",
                            range=models.Range(gte=len(chunks)),
                        ),
                    ]
                )
            ),
        )
        return len(chunks)

    async def retrieve(
        self, query: str, k: int = 5, *, article_hash: str | None = None
    ) -> list[Chunk]:
        """Return the top-``k`` chunks for ``query``.

        When ``article_hash`` is provided the search is scoped to that document;
        omit it for corpus-wide (cross-document) retrieval.
        """
        from qdrant_client import models

        vector = await self._embed_query(query)

        query_filter = None
        if article_hash is not None:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="article_hash",
                        match=models.MatchValue(value=article_hash),
                    )
                ]
            )

        response = await self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=query_filter,
            limit=k,
            with_payload=True,
        )
        return [
            payload_to_chunk(point.payload, getattr(point, "score", None))
            for point in response.points
        ]

    async def delete_source(self, article_hash: str) -> None:
        """Remove all chunks for a source (used on Source deletion)."""
        from qdrant_client import models

        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="article_hash",
                            match=models.MatchValue(value=article_hash),
                        )
                    ]
                )
            ),
        )


# Process-wide singleton so the Qdrant client and embedder are reused across
# requests. The client connects lazily, so constructing this is cheap and safe
# even when Qdrant is unavailable.
_default_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Return the shared :class:`VectorStore` built from environment config."""
    global _default_store
    if _default_store is None:
        from qdrant_client import AsyncQdrantClient

        from app.dspy_files.config import make_embedder

        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        client = AsyncQdrantClient(url=url)
        _default_store = VectorStore(client, make_embedder())
    return _default_store
