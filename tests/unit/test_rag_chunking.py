"""
Unit tests for app/rag/chunking.py - token-aware text chunking for RAG.

Tests the chunk_text() helper and the Chunk model which:
- Split source text into overlapping, token-bounded chunks
- Track sequential chunk indices and best-effort character offsets
- Return empty results for empty/whitespace-only input

NOTE: app.rag.chunking does not exist yet. These tests are written FIRST
(red state) and will fail at import/collection until the implementation lands.
"""

import pytest

from app.rag.chunking import Chunk, chunk_text


@pytest.mark.unit
def test_empty_string_returns_empty_list():
    """Empty input yields no chunks."""
    assert chunk_text("") == []


@pytest.mark.unit
def test_whitespace_only_returns_empty_list():
    """Whitespace-only input yields no chunks."""
    assert chunk_text("   \n\t  \n") == []


@pytest.mark.unit
def test_short_text_returns_single_chunk():
    """Text under max_tokens produces exactly one chunk at index 0."""
    text = "A short article about an illegal fishing vessel seizure."
    chunks = chunk_text(text, max_tokens=800, overlap=100)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert isinstance(chunks[0], Chunk)


@pytest.mark.unit
def test_short_text_chunk_has_full_text():
    """The single chunk for short text should be non-empty."""
    text = "The trawler Ocean Raider was boarded by coast guard officers."
    chunks = chunk_text(text, max_tokens=800, overlap=100)

    assert len(chunks) == 1
    assert chunks[0].text.strip() != ""


@pytest.mark.unit
def test_long_text_returns_multiple_chunks():
    """Long text with a small max_tokens splits into multiple chunks."""
    sentence = "The vessel was caught fishing illegally in protected waters. "
    text = sentence * 200
    chunks = chunk_text(text, max_tokens=50, overlap=10)

    assert len(chunks) > 1


@pytest.mark.unit
def test_long_text_chunk_indices_are_contiguous():
    """Chunk indices form a sequential 0..n-1 run."""
    sentence = "Patrol boats intercepted the unlicensed longliner at dawn. "
    text = sentence * 200
    chunks = chunk_text(text, max_tokens=50, overlap=10)

    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


@pytest.mark.unit
def test_long_text_offsets_are_within_bounds():
    """Every chunk's offsets stay within [0, len(text)] and are ordered."""
    sentence = "Inspectors found undeclared tuna in the vessel's hold. "
    text = sentence * 200
    chunks = chunk_text(text, max_tokens=50, overlap=10)

    for c in chunks:
        assert 0 <= c.start_char <= c.end_char <= len(text)


@pytest.mark.unit
def test_long_text_start_char_non_decreasing():
    """start_char is non-decreasing across consecutive chunks (best-effort)."""
    sentence = "Authorities seized the catch and detained the crew. "
    text = sentence * 200
    chunks = chunk_text(text, max_tokens=50, overlap=10)

    starts = [c.start_char for c in chunks]
    for prev, nxt in zip(starts, starts[1:]):
        assert prev <= nxt


@pytest.mark.unit
def test_consecutive_chunks_overlap():
    """Later chunks share some leading content with the prior chunk's tail."""
    sentence = "The flagless vessel evaded the regional fisheries patrol. "
    text = sentence * 200
    chunks = chunk_text(text, max_tokens=50, overlap=10)

    # Lenient overlap check: at least one adjacent pair shares character
    # ranges, indicating the overlap window is applied.
    assert len(chunks) > 1
    overlapping_pairs = [
        (prev, nxt)
        for prev, nxt in zip(chunks, chunks[1:])
        if nxt.start_char < prev.end_char
    ]
    assert overlapping_pairs


@pytest.mark.unit
def test_all_chunks_are_chunk_instances_with_text():
    """Every returned item is a Chunk with non-empty text."""
    sentence = "The cargo manifest concealed the true species of fish. "
    text = sentence * 200
    chunks = chunk_text(text, max_tokens=50, overlap=10)

    assert chunks
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.text.strip() != ""


@pytest.mark.unit
def test_custom_encoding_model_is_accepted():
    """A custom encoding_model keyword does not break chunking."""
    text = "Short text for encoding model keyword smoke test."
    chunks = chunk_text(text, max_tokens=800, encoding_model="gpt-4o-mini")

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
