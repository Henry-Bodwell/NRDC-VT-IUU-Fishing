"""Token-aware text chunking for retrieval.

Splits a document's text into overlapping, token-bounded chunks using the same
tiktoken encodings the LLM uses, so chunk sizes line up with model token
budgets. Character offsets are tracked best-effort (exact for ASCII text,
clamped to the text length otherwise) for future evidence highlighting.

This is a token-window splitter; it can later be upgraded to a structure-aware
(paragraph/sentence) splitter without changing the public interface.
"""

from __future__ import annotations

from pydantic import BaseModel

import tiktoken


class Chunk(BaseModel):
    """A single retrievable slice of a source document."""

    text: str
    chunk_index: int
    start_char: int = 0
    end_char: int = 0
    # Similarity score, populated only on chunks returned by a retrieval query.
    # Stored chunks leave this None: it is a property of the match, not the text.
    score: float | None = None


def _get_encoding(model: str):
    """Return the tiktoken encoding for ``model``, falling back to cl100k_base."""
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def chunk_text(
    text: str,
    *,
    max_tokens: int = 800,
    overlap: int = 100,
    encoding_model: str = "gpt-4o-mini",
) -> list[Chunk]:
    """Split ``text`` into overlapping, token-bounded chunks.

    Args:
        text: The document text to split.
        max_tokens: Maximum number of tokens per chunk.
        overlap: Number of tokens shared between consecutive chunks.
        encoding_model: Model name whose tiktoken encoding governs token sizing.

    Returns:
        A list of :class:`Chunk` with sequential ``chunk_index`` values. Empty or
        whitespace-only input returns an empty list.
    """
    if not text or not text.strip():
        return []

    encoding = _get_encoding(encoding_model)
    tokens = encoding.encode(text)

    if len(tokens) <= max_tokens:
        return [Chunk(text=text, chunk_index=0, start_char=0, end_char=len(text))]

    # Cumulative character offset at each token boundary. Byte lengths equal
    # character counts for ASCII; for multi-byte text the offsets are clamped to
    # the text length so they remain within bounds (best-effort).
    token_byte_lens = [len(b) for b in encoding.decode_tokens_bytes(tokens)]
    cum_chars = [0]
    for blen in token_byte_lens:
        cum_chars.append(cum_chars[-1] + blen)
    text_len = len(text)

    step = max(1, max_tokens - overlap)
    chunks: list[Chunk] = []
    index = 0
    for start in range(0, len(tokens), step):
        window = tokens[start : start + max_tokens]
        if not window:
            break
        chunk_str = encoding.decode(window)
        start_char = min(cum_chars[start], text_len)
        end_char = min(cum_chars[start + len(window)], text_len)
        chunks.append(
            Chunk(
                text=chunk_str,
                chunk_index=index,
                start_char=start_char,
                end_char=end_char,
            )
        )
        index += 1
        if start + max_tokens >= len(tokens):
            break

    return chunks
