"""
Unit tests for app/rag/incident_segmentation.py - map/reduce incident discovery.

Tests segment_incidents() which:
- Maps a per-chunk DSPy mapper over every chunk to collect anchors
- Aggregates all anchors and calls a DSPy reducer exactly once
- Returns the reducer's discovered IncidentDescriptor list

The mapper/reducer are DSPy modules whose .acall(...) is awaited; they are
mocked here as objects with .acall = AsyncMock(...), matching the idiom in
tests/unit/test_modules.py.

NOTE: app.rag.incident_segmentation does not exist yet. These tests are
written FIRST (red state) and will fail until the implementation lands.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, call

from app.rag.chunking import Chunk
from app.rag.incident_segmentation import IncidentDescriptor, segment_incidents


def make_chunks(*texts: str) -> list[Chunk]:
    """Build a list of Chunks from raw text strings."""
    return [
        Chunk(text=text, chunk_index=i, start_char=0, end_char=len(text))
        for i, text in enumerate(texts)
    ]


def make_mapper(anchors_per_call: list[list[str]]) -> MagicMock:
    """Build a mapper whose acall returns objects with .anchors, in order."""
    mapper = MagicMock()
    outputs = [MagicMock(anchors=anchors) for anchors in anchors_per_call]
    mapper.acall = AsyncMock(side_effect=outputs)
    return mapper


def make_reducer(incidents: list[IncidentDescriptor]) -> MagicMock:
    """Build a reducer whose acall returns an object with .incidents."""
    reducer = MagicMock()
    reducer.acall = AsyncMock(return_value=MagicMock(incidents=incidents))
    return reducer


class TestIncidentDescriptorModel:
    """Tests for the IncidentDescriptor pydantic model."""

    @pytest.mark.unit
    def test_defaults_empty_anchors(self):
        """anchors defaults to an empty list."""
        descriptor = IncidentDescriptor(
            description="A vessel was seized.", retrieval_query="vessel seizure"
        )
        assert descriptor.anchors == []
        assert descriptor.description == "A vessel was seized."
        assert descriptor.retrieval_query == "vessel seizure"


class TestSegmentIncidents:
    """Tests for segment_incidents()."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_mapper_called_once_per_chunk(self):
        """The mapper is awaited once per chunk with that chunk's text."""
        chunks = make_chunks("chunk one", "chunk two", "chunk three")
        mapper = make_mapper([["a1"], ["a2"], ["a3"]])
        reducer = make_reducer([])

        await segment_incidents(chunks, mapper=mapper, reducer=reducer)

        assert mapper.acall.await_count == 3
        mapper.acall.assert_has_awaits(
            [
                call(text="chunk one"),
                call(text="chunk two"),
                call(text="chunk three"),
            ]
        )

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reducer_called_once_with_aggregated_anchors(self):
        """The reducer is awaited exactly once with all aggregated anchors."""
        chunks = make_chunks("c1", "c2", "c3")
        mapper = make_mapper([["a1", "a2"], ["a3"], ["a4", "a5"]])
        reducer = make_reducer([])

        await segment_incidents(chunks, mapper=mapper, reducer=reducer)

        assert reducer.acall.await_count == 1
        reducer.acall.assert_awaited_once_with(anchors=["a1", "a2", "a3", "a4", "a5"])

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_returns_reducer_incidents(self):
        """The reducer's incidents list is returned verbatim."""
        chunks = make_chunks("c1", "c2")
        descriptors = [
            IncidentDescriptor(
                description="Incident A",
                anchors=["a1"],
                retrieval_query="query A",
            ),
            IncidentDescriptor(
                description="Incident B",
                anchors=["a2"],
                retrieval_query="query B",
            ),
        ]
        mapper = make_mapper([["a1"], ["a2"]])
        reducer = make_reducer(descriptors)

        result = await segment_incidents(chunks, mapper=mapper, reducer=reducer)

        assert result == descriptors

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_empty_chunks_returns_empty_and_skips_reducer(self):
        """Empty chunks returns [] and never calls the reducer."""
        mapper = make_mapper([])
        reducer = make_reducer([])

        result = await segment_incidents([], mapper=mapper, reducer=reducer)

        assert result == []
        mapper.acall.assert_not_awaited()
        reducer.acall.assert_not_awaited()
