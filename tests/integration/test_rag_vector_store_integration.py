"""
Integration tests for app/rag/vector_store.py VectorStore against live Qdrant.

These exercise the real index/retrieve/delete roundtrip and require:
- A reachable Qdrant instance (localhost:6333, override QDRANT_URL)
- A real OPENAI_API_KEY (the dummy "test-key" is skipped)

The `qdrant_store` fixture (tests/integration/conftest.py) handles the
service checks and collection lifecycle. These tests are expected to be
skipped in CI where the services are unavailable.

NOTE: app.rag.* does not exist yet -- this is the intended red state.
"""

import uuid
from types import SimpleNamespace

import pytest

from app.rag.chunking import Chunk


def make_source(**overrides):
    """Lightweight source stub.

    VectorStore.index_source only needs ``id`` and ``article_hash``; using a stub
    avoids requiring an initialized Beanie/Mongo connection for a pure
    vector-store roundtrip test.
    """
    fields = {
        "id": uuid.uuid4().hex,
        "article_hash": uuid.uuid4().hex,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _build_chunks() -> list[Chunk]:
    """Two distinct chunks with clearly different topical content."""
    return [
        Chunk(
            text=(
                "The trawler Ocean Raider was boarded by coast guard officers "
                "off the coast and found fishing without a valid license."
            ),
            chunk_index=0,
            start_char=0,
            end_char=100,
        ),
        Chunk(
            text=(
                "Inspectors discovered undeclared bluefin tuna in the vessel's "
                "hold, mislabeled as a lower-value species for export."
            ),
            chunk_index=1,
            start_char=100,
            end_char=200,
        ),
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_store_roundtrip(qdrant_store):
    """Indexed chunks are retrievable, and filtering by source_id is honored."""
    source = make_source(article_text="Roundtrip article body for indexing.")
    chunks = _build_chunks()

    indexed = await qdrant_store.index_source(source, chunks)
    assert indexed == len(chunks)

    results = await qdrant_store.retrieve(
        "vessel fishing without a license",
        k=2,
        source_id=str(source.id),
    )
    assert len(results) >= 1
    retrieved_texts = {c.text for c in results}
    assert retrieved_texts.issubset({c.text for c in chunks})

    # Filtering by an unrelated source_id returns nothing.
    other = await qdrant_store.retrieve(
        "vessel fishing without a license",
        k=2,
        source_id="some-other-source-id",
    )
    assert other == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_index_source_idempotent(qdrant_store):
    """Indexing the same source+chunks twice does not duplicate points."""
    source = make_source(article_text="Idempotency article body for indexing.")
    chunks = _build_chunks()

    first = await qdrant_store.index_source(source, chunks)
    second = await qdrant_store.index_source(source, chunks)

    assert first == len(chunks)
    assert second == len(chunks)

    results = await qdrant_store.retrieve(
        "undeclared mislabeled tuna export",
        k=10,
        source_id=str(source.id),
    )
    # No duplication: distinct points never exceed the number of chunks.
    assert len(results) <= len(chunks)
