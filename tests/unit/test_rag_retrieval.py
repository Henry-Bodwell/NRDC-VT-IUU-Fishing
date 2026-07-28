"""
Unit tests for app/rag/retrieval.py - category-scoped context retrieval.

Tests the category query registry and the retrieval helpers which:
- Map an extraction category to a canned retrieval query
- Optionally narrow that query to a single incident (extra_query)
- Delegate to a VectorStore-like object's retrieve() and join chunk text
"""

import pytest
from unittest.mock import AsyncMock

from app.rag.chunking import Chunk
from app.rag.retrieval import (
    CATEGORY_QUERIES,
    compose_query,
    join_chunks,
    query_for_category,
    retrieve_chunks,
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


class TestComposeQuery:
    """Tests for compose_query()."""

    @pytest.mark.unit
    def test_without_extra_query_returns_category_query(self):
        """With no extra_query the plain category query is used."""
        assert compose_query("vessel") == query_for_category("vessel")

    @pytest.mark.unit
    def test_empty_extra_query_is_ignored(self):
        """An empty extra_query does not alter the category query."""
        assert compose_query("vessel", "") == query_for_category("vessel")

    @pytest.mark.unit
    def test_extra_query_is_prepended_to_category_query(self):
        """extra_query narrows the category query and both parts survive."""
        composed = compose_query("vessel", "the seizure of the Ocean Star")

        assert composed.startswith("the seizure of the Ocean Star")
        assert query_for_category("vessel") in composed

    @pytest.mark.unit
    def test_different_categories_compose_differently(self):
        """The same incident query yields distinct per-category queries."""
        incident = "the seizure of the Ocean Star"

        assert compose_query("vessel", incident) != compose_query("species", incident)


class TestJoinChunks:
    """Tests for join_chunks()."""

    @pytest.mark.unit
    def test_joins_with_blank_line(self):
        """Chunk texts are joined with a blank line separator."""
        chunks = [
            Chunk(text="first chunk", chunk_index=0, start_char=0, end_char=1),
            Chunk(text="second chunk", chunk_index=1, start_char=1, end_char=2),
        ]

        assert join_chunks(chunks) == "first chunk\n\nsecond chunk"

    @pytest.mark.unit
    def test_empty_list_joins_to_empty_string(self):
        """No chunks joins to an empty string."""
        assert join_chunks([]) == ""


class TestRetrieveChunks:
    """Tests for retrieve_chunks()."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_calls_store_retrieve_with_category_query(self):
        """retrieve_chunks delegates to store.retrieve with mapped query/args."""
        store = AsyncMock()
        store.retrieve = AsyncMock(
            return_value=[Chunk(text="a", chunk_index=0, start_char=0, end_char=1)]
        )

        await retrieve_chunks(store, source_id="src-1", category="vessel", k=3)

        store.retrieve.assert_awaited_once_with(
            query_for_category("vessel"), 3, source_id="src-1"
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_returns_chunks_preserving_scores(self):
        """Retrieved Chunk objects are returned as-is, scores intact."""
        store = AsyncMock()
        store.retrieve = AsyncMock(
            return_value=[
                Chunk(text="first", chunk_index=0, start_char=0, end_char=1, score=0.9),
                Chunk(
                    text="second", chunk_index=1, start_char=1, end_char=2, score=0.4
                ),
            ]
        )

        result = await retrieve_chunks(store, source_id="src-2", category="event", k=5)

        assert [c.text for c in result] == ["first", "second"]
        assert [c.score for c in result] == [0.9, 0.4]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_extra_query_is_forwarded_composed(self):
        """extra_query reaches store.retrieve composed with the category query."""
        store = AsyncMock()
        store.retrieve = AsyncMock(return_value=[])

        await retrieve_chunks(
            store,
            source_id="src-5",
            category="crew",
            k=4,
            extra_query="the Ocean Star boarding",
        )

        store.retrieve.assert_awaited_once_with(
            compose_query("crew", "the Ocean Star boarding"), 4, source_id="src-5"
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_default_k_is_five(self):
        """The default k value of 5 is forwarded to store.retrieve."""
        store = AsyncMock()
        store.retrieve = AsyncMock(return_value=[])

        await retrieve_chunks(store, source_id="src-3", category="species")

        store.retrieve.assert_awaited_once_with(
            query_for_category("species"), 5, source_id="src-3"
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_empty_retrieval_returns_empty_list(self):
        """No retrieved chunks returns an empty list."""
        store = AsyncMock()
        store.retrieve = AsyncMock(return_value=[])

        result = await retrieve_chunks(
            store, source_id="src-4", category="summary", k=2
        )

        assert result == []
