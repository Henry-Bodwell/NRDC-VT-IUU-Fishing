"""
Unit tests for new RAG helpers in app/dspy_files/config.py.

Tests the token-counting and embedder helpers which:
- Count tokens for routing decisions
- Decide whether a source is large enough to warrant RAG
- Construct a dspy.Embedder for the configured embedding model

NOTE: These config helpers (count_tokens, should_use_rag, make_embedder,
EMBEDDING_MODEL, RAG_TOKEN_THRESHOLD) do not exist yet. These tests are
written FIRST (red state) and will fail until the implementation lands.
"""

import pytest
from unittest.mock import patch

from app.dspy_files import config
from app.dspy_files.config import (
    EMBEDDING_MODEL,
    RAG_TOKEN_THRESHOLD,
    count_tokens,
    make_embedder,
    should_use_rag,
)


class TestModuleConstants:
    """Tests for the new module-level constants."""

    @pytest.mark.unit
    def test_embedding_model_value(self):
        """EMBEDDING_MODEL is the small OpenAI embedding model."""
        assert EMBEDDING_MODEL == "text-embedding-3-small"

    @pytest.mark.unit
    def test_rag_token_threshold_is_int(self):
        """RAG_TOKEN_THRESHOLD is an integer threshold."""
        assert isinstance(RAG_TOKEN_THRESHOLD, int)
        assert RAG_TOKEN_THRESHOLD > 0


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


class TestShouldUseRag:
    """Tests for should_use_rag() routing decision."""

    @pytest.mark.unit
    def test_value_equal_to_threshold_is_true(self):
        """Token count equal to the threshold triggers RAG (>=)."""
        with patch.object(config, "count_tokens", return_value=100):
            assert should_use_rag("ignored text", threshold=100) is True

    @pytest.mark.unit
    def test_value_below_threshold_is_false(self):
        """Token count one below the threshold does not trigger RAG."""
        with patch.object(config, "count_tokens", return_value=99):
            assert should_use_rag("ignored text", threshold=100) is False

    @pytest.mark.unit
    def test_value_above_threshold_is_true(self):
        """Token count above the threshold triggers RAG."""
        with patch.object(config, "count_tokens", return_value=101):
            assert should_use_rag("ignored text", threshold=100) is True

    @pytest.mark.unit
    def test_none_threshold_uses_module_default(self):
        """When threshold is None, the module-level RAG_TOKEN_THRESHOLD is used."""
        with patch.object(config, "RAG_TOKEN_THRESHOLD", 500), patch.object(
            config, "count_tokens", return_value=500
        ):
            assert should_use_rag("ignored text") is True

        with patch.object(config, "RAG_TOKEN_THRESHOLD", 500), patch.object(
            config, "count_tokens", return_value=499
        ):
            assert should_use_rag("ignored text") is False


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
