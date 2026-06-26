"""Persistent vector store for source-document chunks (Qdrant-backed).

Wraps an async Qdrant client plus a DSPy embedder behind a small interface so
the rest of the pipeline never touches Qdrant types directly. The store is the
source of truth for chunk text + vectors; MongoDB only keeps lightweight
bookkeeping (chunk_count / indexed_at) on the Source.

Indexing is idempotent per article_hash: re-ingesting a document deletes its
existing points before upserting, and point ids are deterministic, so the same
document never accumulates duplicate chunks.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from app.rag.chunking import Chunk

DEFAULT_COLLECTION = "source_chunks"
EMBEDDING_DIM = 1536

# Stable namespace so point ids are deterministic across processes/runs.
_POINT_NAMESPACE = uuid.UUID("6f6b1b3e-2c2a-4f1a-9b9a-1d5c7e2a4f10")


def point_id(article_hash: str, chunk_index: int) -> str:
    """Deterministic Qdrant point id for a chunk of a given document."""
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{article_hash}:{chunk_index}"))


def source_scope_key(source: Any) -> str:
    """Stable retrieval-scoping key for a source.

    Uses the persisted document id when available, falling back to the
    article_hash for not-yet-saved sources so scoping is never ``None``.
    """
    source_id = getattr(source, "id", None)
    if source_id:
        return str(source_id)
    return getattr(source, "article_hash", "")


def chunk_to_payload(source_id: Any, article_hash: str, chunk: Chunk) -> dict:
    """Build the Qdrant payload stored alongside a chunk's vector."""
    return {
        "source_id": str(source_id) if source_id is not None else None,
        "article_hash": article_hash,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "start_char": chunk.start_char,
        "end_char": chunk.end_char,
    }


def payload_to_chunk(payload: dict) -> Chunk:
    """Reconstruct a :class:`Chunk` from a stored Qdrant payload."""
    return Chunk(
        text=payload.get("text", ""),
        chunk_index=payload.get("chunk_index", 0),
        start_char=payload.get("start_char", 0),
        end_char=payload.get("end_char", 0),
    )


class VectorStore:
    """Thin async wrapper around Qdrant + a DSPy embedder."""

    def __init__(self, client, embedder, collection: str = DEFAULT_COLLECTION):
        self.client = client
        self.embedder = embedder
        self.collection = collection

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts off the event loop (the DSPy embedder is synchronous)."""
        vectors = await asyncio.to_thread(self.embedder, texts)
        return [list(map(float, v)) for v in vectors]

    async def ensure_collection(self) -> None:
        """Create the chunk collection if it does not already exist."""
        from qdrant_client import models

        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIM, distance=models.Distance.COSINE
                ),
            )

    async def index_source(self, source: Any, chunks: list[Chunk]) -> int:
        """Embed and upsert a source's chunks; returns the number indexed.

        Idempotent: existing points for the source's article_hash are removed
        before upserting, and point ids are deterministic.
        """
        if not chunks:
            return 0

        from qdrant_client import models

        article_hash = source.article_hash
        scope_key = source_scope_key(source)

        vectors = await self._embed([c.text for c in chunks])

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

        points = [
            models.PointStruct(
                id=point_id(article_hash, chunk.chunk_index),
                vector=vectors[i],
                payload=chunk_to_payload(scope_key, article_hash, chunk),
            )
            for i, chunk in enumerate(chunks)
        ]
        await self.client.upsert(collection_name=self.collection, points=points)
        return len(chunks)

    async def retrieve(
        self, query: str, k: int = 5, *, source_id: str | None = None
    ) -> list[Chunk]:
        """Return the top-``k`` chunks for ``query``.

        When ``source_id`` is provided the search is scoped to that document;
        omit it for corpus-wide (cross-document) retrieval.
        """
        from qdrant_client import models

        vector = (await self._embed([query]))[0]

        query_filter = None
        if source_id is not None:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_id",
                        match=models.MatchValue(value=str(source_id)),
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
        return [payload_to_chunk(point.payload) for point in response.points]

    async def delete_source(self, source_id: Any) -> None:
        """Remove all chunks for a source (used on Source deletion)."""
        from qdrant_client import models

        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_id",
                            match=models.MatchValue(value=str(source_id)),
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
