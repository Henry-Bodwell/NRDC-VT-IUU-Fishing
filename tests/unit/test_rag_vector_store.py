"""
Unit tests for the pure helpers in app/rag/vector_store.py.

Tests ONLY the client-free, deterministic helpers:
- point_id(): stable, deterministic point identifiers
- chunk_to_payload() / payload_to_chunk(): payload round-tripping

The VectorStore class (index_source/retrieve/delete_source) requires a live
Qdrant instance and is covered in the integration suite -- NOT here.

NOTE: app.rag.vector_store does not exist yet. These tests are written FIRST
(red state) and will fail at import/collection until the implementation lands.
"""

import pytest

from app.rag.chunking import Chunk
from app.rag.vector_store import (
    DEFAULT_COLLECTION,
    EMBEDDING_DIM,
    chunk_to_payload,
    payload_to_chunk,
    point_id,
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
