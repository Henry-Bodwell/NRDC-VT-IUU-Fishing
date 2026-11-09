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
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from app.rag.chunking import Chunk

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "source_chunks"
DOCUMENT_COLLECTION = "document_vectors"
EMBEDDING_DIM = 1536

# Document types stored in the document-level collection.
DOC_TYPE_INCIDENT = "incident"
DOC_TYPE_OVERVIEW = "overview"
DOC_TYPE_CLUSTER = "cluster"  # cluster centroids

# Upper bound on cached query vectors (see VectorStore._embed_query).
_QUERY_CACHE_MAX = 128

# Stable namespace so point ids are deterministic across processes/runs.
_POINT_NAMESPACE = uuid.UUID("6f6b1b3e-2c2a-4f1a-9b9a-1d5c7e2a4f10")


def point_id(article_hash: str, chunk_index: int) -> str:
    """Deterministic Qdrant point id for a chunk of a given document."""
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{article_hash}:{chunk_index}"))


def document_point_id(doc_type: str, doc_id: str) -> str:
    """Deterministic Qdrant point id for a document-level vector."""
    return str(uuid.uuid5(_POINT_NAMESPACE, f"doc:{doc_type}:{doc_id}"))


@dataclass
class DocumentHit:
    """A document-level search result."""

    doc_type: str
    doc_id: str
    score: float
    payload: dict = field(default_factory=dict)


@dataclass
class DocumentVector:
    """A stored document-level vector (used by batch jobs such as clustering)."""

    doc_type: str
    doc_id: str
    vector: list[float]
    payload: dict = field(default_factory=dict)


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

    def __init__(
        self,
        client,
        embedder,
        collection: str = DEFAULT_COLLECTION,
        index_fields: Sequence[str] = ("article_hash",),
    ):
        self.client = client
        self.embedder = embedder
        self.collection = collection
        self.index_fields = tuple(index_fields)
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
        """Create the collection and its keyword payload indexes if missing."""
        from qdrant_client import models

        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIM, distance=models.Distance.COSINE
                ),
            )

        # Scoped retrieval, re-indexing and deletion all filter on these fields
        # (article_hash for chunks, doc_type for documents); without a payload
        # index those are unindexed scans. Qdrant treats re-creating an
        # existing index as a no-op, so this is safe to run on every startup.
        for field_name in self.index_fields:
            try:
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception as e:
                logger.debug(f"Payload index for '{field_name}' not created: {e}")

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

    # ── Document-level vectors ──────────────────────────────────────
    # One vector per incident / overview, keyed on (doc_type, doc_id). Used for
    # cross-document similarity (duplicate detection, clustering), never for
    # extraction-time retrieval.

    @staticmethod
    def _doc_type_filter(doc_types: Iterable[str] | None):
        from qdrant_client import models

        if not doc_types:
            return None
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_type", match=models.MatchAny(any=list(doc_types))
                )
            ]
        )

    async def upsert_documents(
        self, items: Sequence[tuple[str, str, str, dict]]
    ) -> int:
        """Embed and upsert ``(doc_type, doc_id, text, extra_payload)`` items.

        Idempotent: the point id is derived from (doc_type, doc_id), so
        re-indexing a document overwrites its previous vector.
        """
        if not items:
            return 0

        from qdrant_client import models

        await self._ensure_ready()
        vectors = await self._embed([text for _, _, text, _ in items])
        points = [
            models.PointStruct(
                id=document_point_id(doc_type, doc_id),
                vector=vectors[i],
                payload={**extra, "doc_type": doc_type, "doc_id": doc_id},
            )
            for i, (doc_type, doc_id, _, extra) in enumerate(items)
        ]
        await self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    async def upsert_vectors(
        self, items: Sequence[tuple[str, str, Sequence[float], dict]]
    ) -> int:
        """Upsert precomputed ``(doc_type, doc_id, vector, extra_payload)`` items.

        Used for vectors that are not embeddings of text, e.g. cluster centroids.
        """
        if not items:
            return 0

        from qdrant_client import models

        await self._ensure_ready()
        points = [
            models.PointStruct(
                id=document_point_id(doc_type, doc_id),
                vector=list(map(float, vector)),
                payload={**extra, "doc_type": doc_type, "doc_id": doc_id},
            )
            for doc_type, doc_id, vector, extra in items
        ]
        await self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    async def get_document_vector(
        self, doc_type: str, doc_id: str
    ) -> list[float] | None:
        """Return the stored vector for a document, or ``None`` if not indexed."""
        await self._ensure_ready()
        records = await self.client.retrieve(
            collection_name=self.collection,
            ids=[document_point_id(doc_type, doc_id)],
            with_vectors=True,
            with_payload=False,
        )
        if not records:
            return None
        vector = records[0].vector
        return list(map(float, vector)) if vector is not None else None

    async def get_document_vectors(
        self, keys: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], list[float]]:
        """Return stored vectors for ``(doc_type, doc_id)`` keys (missing ones omitted)."""
        if not keys:
            return {}
        await self._ensure_ready()
        by_point = {document_point_id(t, i): (t, i) for t, i in keys}
        records = await self.client.retrieve(
            collection_name=self.collection,
            ids=list(by_point),
            with_vectors=True,
            with_payload=False,
        )
        return {
            by_point[str(record.id)]: list(map(float, record.vector))
            for record in records
            if record.vector is not None and str(record.id) in by_point
        }

    async def similar_to_vector(
        self,
        vector: Sequence[float],
        k: int = 10,
        *,
        doc_types: Iterable[str] | None = None,
        score_threshold: float | None = None,
        exclude: tuple[str, str] | None = None,
    ) -> list[DocumentHit]:
        """Return the top-``k`` documents nearest ``vector``.

        ``exclude`` is a ``(doc_type, doc_id)`` pair to leave out (typically the
        query document itself).
        """
        from qdrant_client import models

        query_filter = self._doc_type_filter(doc_types)
        if exclude is not None:
            query_filter = query_filter or models.Filter()
            query_filter.must_not = [
                models.HasIdCondition(has_id=[document_point_id(*exclude)])
            ]

        response = await self.client.query_points(
            collection_name=self.collection,
            query=list(vector),
            query_filter=query_filter,
            limit=k,
            score_threshold=score_threshold,
            with_payload=True,
        )
        hits = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                DocumentHit(
                    doc_type=payload.get("doc_type", ""),
                    doc_id=payload.get("doc_id", ""),
                    score=float(getattr(point, "score", 0.0) or 0.0),
                    payload=payload,
                )
            )
        return hits

    async def similar_to_document(
        self,
        doc_type: str,
        doc_id: str,
        k: int = 10,
        *,
        doc_types: Iterable[str] | None = None,
        score_threshold: float | None = None,
    ) -> list[DocumentHit]:
        """Return the top-``k`` documents nearest an already-indexed document.

        Returns an empty list when the query document has no stored vector.
        """
        vector = await self.get_document_vector(doc_type, doc_id)
        if vector is None:
            return []
        return await self.similar_to_vector(
            vector,
            k,
            doc_types=doc_types,
            score_threshold=score_threshold,
            exclude=(doc_type, doc_id),
        )

    async def scroll_vectors(
        self, doc_types: Iterable[str] | None = None, batch_size: int = 256
    ) -> list[DocumentVector]:
        """Return every stored document vector (optionally filtered by type)."""
        await self._ensure_ready()
        scroll_filter = self._doc_type_filter(doc_types)
        results: list[DocumentVector] = []
        offset = None
        while True:
            records, offset = await self.client.scroll(
                collection_name=self.collection,
                scroll_filter=scroll_filter,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for record in records:
                payload = record.payload or {}
                if record.vector is None:
                    continue
                results.append(
                    DocumentVector(
                        doc_type=payload.get("doc_type", ""),
                        doc_id=payload.get("doc_id", ""),
                        vector=list(map(float, record.vector)),
                        payload=payload,
                    )
                )
            if offset is None:
                break
        return results

    async def delete_document(self, doc_type: str, doc_id: str) -> None:
        """Remove a document-level vector (no-op if it was never indexed)."""
        from qdrant_client import models

        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(
                points=[document_point_id(doc_type, doc_id)]
            ),
        )


# Process-wide singletons so the Qdrant client and embedder are reused across
# requests. The client connects lazily, so constructing these is cheap and safe
# even when Qdrant is unavailable.
_default_store: VectorStore | None = None
_document_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Return the shared chunk :class:`VectorStore` built from environment config."""
    global _default_store
    if _default_store is None:
        from qdrant_client import AsyncQdrantClient

        from app.dspy_files.config import make_embedder

        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        client = AsyncQdrantClient(url=url)
        _default_store = VectorStore(client, make_embedder())
    return _default_store


def get_document_store() -> VectorStore:
    """Return the shared document-level :class:`VectorStore`.

    Shares the Qdrant client and embedder with the chunk store; only the
    collection and its payload indexes differ.
    """
    global _document_store
    if _document_store is None:
        chunk_store = get_vector_store()
        _document_store = VectorStore(
            chunk_store.client,
            chunk_store.embedder,
            collection=DOCUMENT_COLLECTION,
            index_fields=("doc_type", "doc_id"),
        )
    return _document_store
