"""
Unit tests for app/rag/retrieval.py - category-scoped context retrieval.

Tests the category query registry and the retrieve_context() coroutine which:
- Maps an extraction category to a canned retrieval query
- Delegates to a VectorStore-like object's retrieve() and joins chunk text

NOTE: app.rag.retrieval does not exist yet. These tests are written FIRST
(red state) and will fail at import/collection until the implementation lands.
"""

import pytest
from unittest.mock import AsyncMock

from app.rag.chunking import Chunk
from app.rag.retrieval import (
    CATEGORY_QUERIES,
    query_for_category,
    retrieve_context,
)

EXPECTED_CATEGORIES = {
    "vessel",
    "crew",
    "labor",
    "catch",
    "compliance",
    "species",
    "event",
    "transshipment",
    "aquaculture",
    "trade_distribution",
    "products",
    "classification",
    "summary",
}


class TestCategoryQueries:
    """Tests for the CATEGORY_QUERIES registry."""

    @pytest.mark.unit
    def test_keys_match_expected_set(self):
        """The category keys are exactly the expected set."""
        assert set(CATEGORY_QUERIES.keys()) == EXPECTED_CATEGORIES

    @pytest.mark.unit
    def test_every_value_is_non_empty_string(self):
        """Every query value is a non-empty string."""
        for category, query in CATEGORY_QUERIES.items():
            assert isinstance(query, str), category
            assert query.strip() != "", category


class TestQueryForCategory:
    """Tests for query_for_category()."""

    @pytest.mark.unit
    def test_known_category_returns_registered_query(self):
        """A known category returns its registered query string."""
        assert query_for_category("vessel") == CATEGORY_QUERIES["vessel"]

    @pytest.mark.unit
    def test_unknown_category_raises_key_error(self):
        """An unknown category raises KeyError."""
        with pytest.raises(KeyError):
            query_for_category("not_a_real_category")


class TestRetrieveContext:
    """Tests for retrieve_context()."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_calls_store_retrieve_with_category_query(self):
        """retrieve_context delegates to store.retrieve with mapped query/args."""
        store = AsyncMock()
        store.retrieve = AsyncMock(
            return_value=[Chunk(text="a", chunk_index=0, start_char=0, end_char=1)]
        )

        await retrieve_context(store, source_id="src-1", category="vessel", k=3)

        store.retrieve.assert_awaited_once_with(
            query_for_category("vessel"), 3, source_id="src-1"
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_joins_chunk_text_with_double_newline(self):
        """Returned chunk texts are joined with a blank line separator."""
        store = AsyncMock()
        store.retrieve = AsyncMock(
            return_value=[
                Chunk(text="first chunk", chunk_index=0, start_char=0, end_char=1),
                Chunk(text="second chunk", chunk_index=1, start_char=1, end_char=2),
            ]
        )

        result = await retrieve_context(store, source_id="src-2", category="event", k=5)

        assert result == "first chunk\n\nsecond chunk"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_default_k_is_five(self):
        """The default k value of 5 is forwarded to store.retrieve."""
        store = AsyncMock()
        store.retrieve = AsyncMock(return_value=[])

        await retrieve_context(store, source_id="src-3", category="species")

        store.retrieve.assert_awaited_once_with(
            query_for_category("species"), 5, source_id="src-3"
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_empty_retrieval_returns_empty_string(self):
        """No retrieved chunks joins to an empty string."""
        store = AsyncMock()
        store.retrieve = AsyncMock(return_value=[])

        result = await retrieve_context(
            store, source_id="src-4", category="summary", k=2
        )

        assert result == ""
