"""
Integration-test fixtures for the RAG vector store.

Provides a `qdrant_store` fixture that connects to a live Qdrant instance
(localhost:6333 by default, override via QDRANT_URL) and yields a real
VectorStore backed by a real OpenAI embedder. The fixture:
- Skips the test if Qdrant is unreachable.
- Skips the test if OPENAI_API_KEY is missing or the dummy "test-key".
- Uses a unique throwaway collection per test and deletes it on teardown.

These tests require live services and are expected to be skipped in CI.

NOTE: app.rag.vector_store / app.dspy_files.config helpers do not exist yet.
This fixture will fail at import until the implementation lands; that is the
intended red state for the RAG rework.
"""

import os
import uuid

import pytest

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")


def _qdrant_reachable(url: str) -> bool:
    """Best-effort reachability probe for a Qdrant HTTP endpoint."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url, timeout=2.0)
        client.get_collections()
        client.close()
        return True
    except Exception:
        return False


def _openai_key_available() -> bool:
    """True only when a real (non-dummy) OpenAI key is configured."""
    key = os.getenv("OPENAI_API_KEY")
    return bool(key) and key != "test-key"


@pytest.fixture
async def qdrant_store():
    """
    Yield a real VectorStore wired to live Qdrant + a real embedder.

    Skips when Qdrant is unreachable or no real OpenAI key is present.
    Each test gets its own unique collection, dropped on teardown.
    """
    if not _qdrant_reachable(QDRANT_URL):
        pytest.skip(f"Qdrant not reachable at {QDRANT_URL}")
    if not _openai_key_available():
        pytest.skip("OPENAI_API_KEY missing or dummy 'test-key'")

    from qdrant_client import AsyncQdrantClient

    from app.dspy_files.config import make_embedder
    from app.rag.vector_store import VectorStore

    collection = f"test_source_chunks_{uuid.uuid4().hex}"
    client = AsyncQdrantClient(url=QDRANT_URL)
    embedder = make_embedder()
    store = VectorStore(client, embedder, collection=collection)

    await store.ensure_collection()

    try:
        yield store
    finally:
        try:
            await client.delete_collection(collection_name=collection)
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass
