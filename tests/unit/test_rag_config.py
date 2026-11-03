"""
Unit tests for the RAG helpers in app/dspy_files/config.py.

Tests the token-counting and embedder helpers which:
- Count tokens (for reporting and backfill prioritisation)
- Construct a dspy.Embedder for the configured embedding model

Note there is deliberately no size-based routing helper: every source is
chunked, indexed and extracted via retrieval regardless of length.
"""

import pytest
from unittest.mock import patch

from app.dspy_files import config
from app.dspy_files.config import (
    EMBEDDING_MODEL,
    count_tokens,
    make_embedder,
)


class TestModuleConstants:
    """Tests for the module-level constants."""

    @pytest.mark.unit
    def test_embedding_model_value(self):
        """EMBEDDING_MODEL is the small OpenAI embedding model."""
        assert EMBEDDING_MODEL == "text-embedding-3-small"

    @pytest.mark.unit
    def test_no_size_based_rag_gate_remains(self):
        """The size gate is gone: retrieval is the uniform path for all sources."""
        assert not hasattr(config, "should_use_rag")
        assert not hasattr(config, "RAG_TOKEN_THRESHOLD")


class TestCountTokens:
    """Tests for count_tokens()."""

    @pytest.mark.unit
    def test_empty_string_is_zero_tokens(self):
        """An empty string has zero tokens."""
        assert count_tokens("") == 0

    @pytest.mark.unit
    def test_non_empty_string_has_positive_tokens(self):
        """Non-empty text has a positive token count."""
        assert count_tokens("hello world") > 0

    @pytest.mark.unit
    def test_longer_text_has_at_least_as_many_tokens(self):
        """Longer text yields at least as many tokens as shorter text."""
        short = count_tokens("hello world")
        longer = count_tokens("hello world " * 50)
        assert longer >= short


class TestMakeEmbedder:
    """Tests for make_embedder()."""

    @pytest.mark.unit
    def test_constructs_dspy_embedder_with_default_model(self):
        """make_embedder constructs a dspy.Embedder for the configured model."""
        with patch("dspy.Embedder") as mock_embedder:
            make_embedder()

        assert mock_embedder.called
        call = mock_embedder.call_args
        all_args = list(call.args) + list(call.kwargs.values())
        assert "text-embedding-3-small" in all_args

    @pytest.mark.unit
    def test_returns_constructed_embedder(self):
        """The constructed dspy.Embedder instance is returned."""
        with patch("dspy.Embedder") as mock_embedder:
            sentinel = mock_embedder.return_value
            result = make_embedder()

        assert result is sentinel

    @pytest.mark.unit
    def test_custom_model_is_passed_through(self):
        """A custom model string is forwarded to dspy.Embedder."""
        with patch("dspy.Embedder") as mock_embedder:
            make_embedder(model="text-embedding-3-large")

        call = mock_embedder.call_args
        all_args = list(call.args) + list(call.kwargs.values())
        assert "text-embedding-3-large" in all_args
