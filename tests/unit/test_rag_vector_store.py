"""
Unit tests for the pure helpers in app/rag/vector_store.py.

Tests the client-free, deterministic helpers:
- point_id(): stable, deterministic point identifiers
- chunk_to_payload() / payload_to_chunk(): payload round-tripping
- VectorStore._embed_query(): the process-wide query-vector cache

- index_source()/delete_source() call shapes against a mocked Qdrant client:
  article_hash keying, upsert-before-tail-delete, lazy collection creation

End-to-end behavior against a live Qdrant instance is covered in the
integration suite.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.rag.chunking import Chunk
from app.rag.vector_store import (
    DEFAULT_COLLECTION,
    EMBEDDING_DIM,
    VectorStore,
    _QUERY_CACHE_MAX,
    chunk_to_payload,
    payload_to_chunk,
    point_id,
    source_scope_key,
)


class TestModuleConstants:
    """Tests for module-level constants."""

    @pytest.mark.unit
    def test_default_collection_name(self):
        assert DEFAULT_COLLECTION == "source_chunks"

    @pytest.mark.unit
    def test_embedding_dim(self):
        assert EMBEDDING_DIM == 1536


class TestPointId:
    """Tests for point_id() determinism."""

    @pytest.mark.unit
    def test_deterministic_for_same_inputs(self):
        """Same article_hash + chunk_index yields the same id across calls."""
        first = point_id("abc123hash", 0)
        second = point_id("abc123hash", 0)
        assert first == second

    @pytest.mark.unit
    def test_differs_by_chunk_index(self):
        """Different chunk indices yield different ids."""
        assert point_id("abc123hash", 0) != point_id("abc123hash", 1)

    @pytest.mark.unit
    def test_differs_by_hash(self):
        """Different article hashes yield different ids."""
        assert point_id("abc123hash", 0) != point_id("def456hash", 0)

    @pytest.mark.unit
    def test_returns_string(self):
        """point_id returns a string identifier."""
        assert isinstance(point_id("abc123hash", 0), str)


class TestPayloadRoundTrip:
    """Tests for chunk_to_payload() and payload_to_chunk()."""

    @pytest.mark.unit
    def test_chunk_to_payload_has_expected_keys(self):
        """Payload carries source_id, article_hash, chunk_index and text."""
        chunk = Chunk(text="some chunk text", chunk_index=3, start_char=10, end_char=25)
        payload = chunk_to_payload("source-id-1", "hash-1", chunk)

        assert payload["source_id"] == "source-id-1"
        assert payload["article_hash"] == "hash-1"
        assert payload["chunk_index"] == 3
        assert payload["text"] == "some chunk text"

    @pytest.mark.unit
    def test_round_trip_preserves_text_and_index(self):
        """payload_to_chunk inverts chunk_to_payload for text and chunk_index."""
        chunk = Chunk(
            text="round trip text", chunk_index=7, start_char=100, end_char=200
        )
        payload = chunk_to_payload("source-id-2", "hash-2", chunk)
        restored = payload_to_chunk(payload)

        assert isinstance(restored, Chunk)
        assert restored.text == chunk.text
        assert restored.chunk_index == chunk.chunk_index

    @pytest.mark.unit
    def test_payload_to_chunk_defaults_offsets_to_zero(self):
        """Missing start/end char offsets default to 0."""
        payload = {
            "source_id": "source-id-3",
            "article_hash": "hash-3",
            "chunk_index": 1,
            "text": "no offsets provided",
        }
        restored = payload_to_chunk(payload)

        assert restored.start_char == 0
        assert restored.end_char == 0
        assert restored.text == "no offsets provided"
        assert restored.chunk_index == 1

    @pytest.mark.unit
    def test_stored_chunks_have_no_score(self):
        """A score is a property of a match, so stored payloads carry none."""
        chunk = Chunk(text="stored", chunk_index=0, start_char=0, end_char=6)
        payload = chunk_to_payload("source-id-4", "hash-4", chunk)

        assert "score" not in payload
        assert payload_to_chunk(payload).score is None

    @pytest.mark.unit
    def test_score_is_attached_when_supplied(self):
        """payload_to_chunk records the similarity score for query results."""
        chunk = Chunk(text="matched", chunk_index=0, start_char=0, end_char=7)
        payload = chunk_to_payload("source-id-5", "hash-5", chunk)

        assert payload_to_chunk(payload, 0.8125).score == pytest.approx(0.8125)


class TestQueryVectorCache:
    """Tests for VectorStore._embed_query() caching.

    The 13 category queries are static and now run on every document, so each
    must be embedded once per process rather than once per extraction.
    """

    @staticmethod
    def _store() -> VectorStore:
        """A store whose embedder returns a fixed vector and counts calls."""
        embedder = MagicMock(side_effect=lambda texts: [[0.1, 0.2, 0.3]] * len(texts))
        return VectorStore(client=MagicMock(), embedder=embedder)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_repeated_query_embeds_once(self):
        """The same query string is embedded only on first use."""
        store = self._store()

        first = await store._embed_query("vessel name and flag state")
        second = await store._embed_query("vessel name and flag state")

        assert first == second
        assert store.embedder.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_distinct_queries_embed_separately(self):
        """Different query strings each require their own embedding call."""
        store = self._store()

        await store._embed_query("vessel name and flag state")
        await store._embed_query("crew nationality and recruitment")

        assert store.embedder.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_cache_is_bounded(self):
        """Document-specific queries cannot grow the cache without limit."""
        store = self._store()

        for i in range(_QUERY_CACHE_MAX + 25):
            await store._embed_query(f"incident number {i}")

        assert len(store._query_vectors) == _QUERY_CACHE_MAX


class TestArticleHashKeying:
    """Chunks are scoped and deleted by article_hash, never the Mongo id.

    Sources are indexed during ingestion before insert, when ``id`` is None, so
    any id-based key would orphan their chunks once the source is saved.
    """

    @staticmethod
    def _store() -> VectorStore:
        client = MagicMock()
        for method in (
            "collection_exists",
            "create_collection",
            "create_payload_index",
            "upsert",
            "delete",
        ):
            setattr(client, method, AsyncMock())
        client.collection_exists.return_value = True
        embedder = MagicMock(side_effect=lambda texts: [[0.0] * 3] * len(texts))
        return VectorStore(client=client, embedder=embedder)

    @staticmethod
    def _filter_values(delete_call) -> dict:
        """Map field name -> match value or range for a delete() call's filter."""
        must = delete_call.kwargs["points_selector"].filter.must
        return {
            cond.key: (cond.match.value if cond.match is not None else cond.range)
            for cond in must
        }

    @pytest.mark.unit
    def test_scope_key_is_article_hash_before_and_after_insert(self):
        unsaved = MagicMock(id=None, article_hash="hash-1")
        saved = MagicMock(id="65f0c0ffee", article_hash="hash-1")
        assert source_scope_key(unsaved) == source_scope_key(saved) == "hash-1"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_unsaved_source_chunks_are_deletable_by_hash(self):
        """Chunks indexed with id=None are matched by delete_source(article_hash)."""
        store = self._store()
        source = MagicMock(id=None, article_hash="hash-1")
        chunks = [Chunk(text="a", chunk_index=0), Chunk(text="b", chunk_index=1)]

        await store.index_source(source, chunks)
        points = store.client.upsert.await_args.kwargs["points"]
        assert {pt.payload["article_hash"] for pt in points} == {"hash-1"}

        store.client.delete.reset_mock()
        await store.delete_source("hash-1")
        assert self._filter_values(store.client.delete.await_args) == {
            "article_hash": "hash-1"
        }

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reindex_upserts_before_deleting_only_the_stale_tail(self):
        """A failed upsert can never leave the source with no chunks."""
        store = self._store()
        calls: list[str] = []
        store.client.upsert.side_effect = lambda **kw: calls.append("upsert")
        store.client.delete.side_effect = lambda **kw: calls.append("delete")
        chunks = [Chunk(text="a", chunk_index=0), Chunk(text="b", chunk_index=1)]

        await store.index_source(MagicMock(id=None, article_hash="h"), chunks)

        assert calls == ["upsert", "delete"]
        values = self._filter_values(store.client.delete.await_args)
        assert values["article_hash"] == "h"
        assert values["chunk_index"].gte == len(chunks)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_failed_upsert_deletes_nothing(self):
        store = self._store()
        store.client.upsert.side_effect = RuntimeError("qdrant down")

        with pytest.raises(RuntimeError):
            await store.index_source(
                MagicMock(id=None, article_hash="h"), [Chunk(text="a", chunk_index=0)]
            )

        store.client.delete.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_collection_is_created_lazily_after_startup_failure(self):
        """If startup could not reach Qdrant, the first index creates the collection."""
        store = self._store()
        store.client.collection_exists.side_effect = [
            ConnectionError("not ready"),
            False,
        ]

        with pytest.raises(ConnectionError):
            await store.ensure_collection()

        await store.index_source(
            MagicMock(id=None, article_hash="h"), [Chunk(text="a", chunk_index=0)]
        )

        store.client.create_collection.assert_awaited_once()
        store.client.upsert.assert_awaited_once()

        # Once ready, later indexing does not re-check the collection.
        await store.index_source(
            MagicMock(id=None, article_hash="h"), [Chunk(text="a", chunk_index=0)]
        )
        assert store.client.collection_exists.await_count == 2
