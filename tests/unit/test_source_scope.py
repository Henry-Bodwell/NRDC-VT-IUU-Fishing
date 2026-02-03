"""
Unit tests for source_scope.py - Article classification module.

Tests the SourceScope class which classifies articles into:
- Single Incident
- Multiple Incidents
- Industry Overview
- Unrelated to IUU Fishing
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.sources import ArticleScopeClassification
from app.dspy_files.source_scope import SourceScope


def create_mock_source(
    url: str = "https://example.com/test-article",
    article_text: str = "Test article text",
    title: str = "Test Title",
    author: str = "Test Author",
    publisher: str = "Test News",
    source_type: str = "news",
    status: str = "extracted",
    article_scope: ArticleScopeClassification | None = None,
):
    """Create a mock Source object that doesn't require Beanie initialization."""
    mock_source = MagicMock()
    mock_source.url = url
    mock_source.article_text = article_text
    mock_source.title = title
    mock_source.author = author
    mock_source.publisher = publisher
    mock_source.source_type = source_type
    mock_source.status = status
    mock_source.article_scope = article_scope
    return mock_source


@pytest.fixture
def sample_source_unclassified():
    """Create an unclassified Source for testing."""
    return create_mock_source(
        url="https://example.com/test-article",
        article_text="A fishing vessel named Ocean Raider was caught illegally fishing in protected waters on January 15, 2024. The vessel was seized by authorities.",
        title="Illegal Fishing Vessel Seized",
        article_scope=None,
    )


@pytest.fixture
def sample_source_classified():
    """Create an already classified Source for testing."""
    return create_mock_source(
        url="https://example.com/classified-article",
        article_text="Test article text",
        title="Test Article",
        article_scope=ArticleScopeClassification(
            articleType="Single Incident",
            confidence=0.95,
        ),
    )


@pytest.fixture
def mock_classification_tool():
    """Create a mock for the dspy.ChainOfThought classification tool."""
    mock_tool = MagicMock()
    mock_tool.acall = AsyncMock()
    return mock_tool


class TestSourceScopeInit:
    """Tests for SourceScope initialization."""

    @pytest.mark.unit
    def test_init_creates_classification_tool(self):
        """Test that SourceScope creates a ChainOfThought classification tool."""
        with patch("dspy.ChainOfThought") as mock_cot:
            scope = SourceScope()
            mock_cot.assert_called_once()
            assert scope.classification_tool is not None


class TestSourceScopeRun:
    """Tests for SourceScope.run() method."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_classifies_unclassified_source(
        self, sample_source_unclassified, mock_classification_tool
    ):
        """Test that run() classifies an unclassified source."""
        # Setup mock response
        mock_classification = ArticleScopeClassification(
            articleType="Single Incident",
            confidence=0.92,
        )
        mock_prediction = MagicMock()
        mock_prediction.classification = mock_classification
        mock_classification_tool.acall.return_value = mock_prediction

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(sample_source_unclassified)

        # Verify classification was called
        mock_classification_tool.acall.assert_called_once_with(
            source=sample_source_unclassified
        )

        # Verify source was updated
        assert result.article_scope is not None
        assert result.article_scope.articleType == "Single Incident"
        assert result.article_scope.confidence == 0.92

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_skips_already_classified_source(
        self, sample_source_classified, mock_classification_tool
    ):
        """Test that run() skips classification if source is already classified."""
        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(sample_source_classified)

        # Verify classification was NOT called
        mock_classification_tool.acall.assert_not_called()

        # Verify original classification is preserved
        assert result.article_scope.articleType == "Single Incident"
        assert result.article_scope.confidence == 0.95

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_classifies_as_multiple_incidents(
        self, sample_source_unclassified, mock_classification_tool
    ):
        """Test classification as Multiple Incidents."""
        mock_classification = ArticleScopeClassification(
            articleType="Multiple Incidents",
            confidence=0.88,
        )
        mock_prediction = MagicMock()
        mock_prediction.classification = mock_classification
        mock_classification_tool.acall.return_value = mock_prediction

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(sample_source_unclassified)

        assert result.article_scope.articleType == "Multiple Incidents"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_classifies_as_industry_overview(
        self, sample_source_unclassified, mock_classification_tool
    ):
        """Test classification as Industry Overview."""
        mock_classification = ArticleScopeClassification(
            articleType="Industry Overview",
            confidence=0.85,
        )
        mock_prediction = MagicMock()
        mock_prediction.classification = mock_classification
        mock_classification_tool.acall.return_value = mock_prediction

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(sample_source_unclassified)

        assert result.article_scope.articleType == "Industry Overview"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_classifies_as_unrelated(
        self, sample_source_unclassified, mock_classification_tool
    ):
        """Test classification as Unrelated to IUU Fishing."""
        mock_classification = ArticleScopeClassification(
            articleType="Unrelated to IUU Fishing",
            confidence=0.78,
        )
        mock_prediction = MagicMock()
        mock_prediction.classification = mock_classification
        mock_classification_tool.acall.return_value = mock_prediction

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(sample_source_unclassified)

        assert result.article_scope.articleType == "Unrelated to IUU Fishing"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_raises_on_llm_error(
        self, sample_source_unclassified, mock_classification_tool
    ):
        """Test that run() raises an exception on LLM error."""
        mock_classification_tool.acall.side_effect = Exception("LLM API Error")

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            with pytest.raises(Exception, match="LLM API Error"):
                await scope.run(sample_source_unclassified)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_returns_source_object(
        self, sample_source_unclassified, mock_classification_tool
    ):
        """Test that run() returns the Source object."""
        mock_classification = ArticleScopeClassification(
            articleType="Single Incident",
            confidence=0.90,
        )
        mock_prediction = MagicMock()
        mock_prediction.classification = mock_classification
        mock_classification_tool.acall.return_value = mock_prediction

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(sample_source_unclassified)

        assert result is sample_source_unclassified
        assert result.url == "https://example.com/test-article"


class TestSourceScopeEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_with_empty_article_text(self, mock_classification_tool):
        """Test classification with empty article text."""
        source = create_mock_source(
            url="https://example.com/empty",
            article_text="",
            title="Empty Article",
        )

        mock_classification = ArticleScopeClassification(
            articleType="Unrelated to IUU Fishing",
            confidence=0.5,
        )
        mock_prediction = MagicMock()
        mock_prediction.classification = mock_classification
        mock_classification_tool.acall.return_value = mock_prediction

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(source)

        # Should still process and return a classification
        assert result.article_scope is not None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_with_low_confidence(self, mock_classification_tool):
        """Test classification with low confidence score."""
        source = create_mock_source(
            url="https://example.com/ambiguous",
            article_text="Some ambiguous text about fishing that could be related to IUU.",
            title="Ambiguous Article",
        )

        mock_classification = ArticleScopeClassification(
            articleType="Single Incident",
            confidence=0.51,  # Just above threshold
        )
        mock_prediction = MagicMock()
        mock_prediction.classification = mock_classification
        mock_classification_tool.acall.return_value = mock_prediction

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(source)

        assert result.article_scope.confidence == 0.51

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_preserves_source_metadata(self, mock_classification_tool):
        """Test that run() preserves all source metadata after classification."""
        source = create_mock_source(
            url="https://example.com/metadata-test",
            article_text="Test article about IUU fishing incident.",
            title="Metadata Test",
            author="John Doe",
            publisher="News Corp",
            source_type="news",
            status="extracted",
        )

        mock_classification = ArticleScopeClassification(
            articleType="Single Incident",
            confidence=0.90,
        )
        mock_prediction = MagicMock()
        mock_prediction.classification = mock_classification
        mock_classification_tool.acall.return_value = mock_prediction

        with patch("dspy.ChainOfThought", return_value=mock_classification_tool):
            scope = SourceScope()
            result = await scope.run(source)

        # Verify all metadata is preserved
        assert result.url == "https://example.com/metadata-test"
        assert result.title == "Metadata Test"
        assert result.author == "John Doe"
        assert result.publisher == "News Corp"
        assert result.source_type == "news"
        assert result.status == "extracted"
