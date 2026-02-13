"""
Unit tests for analysis_pipeline.py - Article analysis routing module.

Tests the AnalysisPipeline class which:
- Classifies articles by scope
- Routes to appropriate analysis module based on classification
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import dspy

from app.models.sources import ArticleScopeClassification
from app.dspy_files.analysis_pipeline import AnalysisPipeline


def create_mock_source(
    url: str = "https://example.com/test",
    article_text: str = "Test article text",
    article_hash: str = "abc123hash",
    article_scope: ArticleScopeClassification | None = None,
):
    """Create a mock Source object."""
    mock_source = MagicMock()
    mock_source.url = url
    mock_source.article_text = article_text
    mock_source.article_hash = article_hash
    mock_source.article_scope = article_scope
    return mock_source


@pytest.fixture
def mock_setup_dspy():
    """Mock the setup_dspy function."""
    with patch("app.dspy_files.analysis_pipeline.setup_dspy") as mock:
        mock.return_value = MagicMock()
        yield mock


@pytest.fixture
def mock_source_scope():
    """Mock SourceScope class."""
    with patch("app.dspy_files.analysis_pipeline.SourceScope") as mock:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock()
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_incident_module():
    """Mock IncidentAnalysisModule class."""
    with patch("app.dspy_files.analysis_pipeline.IncidentAnalysisModule") as mock:
        mock_instance = MagicMock()
        mock_instance.acall = AsyncMock()
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_overview_module():
    """Mock IndustryOverviewModule class."""
    with patch("app.dspy_files.analysis_pipeline.IndustryOverviewModule") as mock:
        mock_instance = MagicMock()
        mock_instance.acall = AsyncMock()
        mock.return_value = mock_instance
        yield mock_instance


class TestAnalysisPipelineInit:
    """Tests for AnalysisPipeline initialization."""

    @pytest.mark.unit
    def test_init_creates_all_tools(self):
        """Test that AnalysisPipeline initializes all required components."""
        with patch("app.dspy_files.analysis_pipeline.setup_dspy") as mock_setup:
            with patch("app.dspy_files.analysis_pipeline.SourceScope") as mock_scope:
                with patch(
                    "app.dspy_files.analysis_pipeline.IncidentAnalysisModule"
                ) as mock_incident:
                    with patch(
                        "app.dspy_files.analysis_pipeline.IndustryOverviewModule"
                    ) as mock_overview:
                        mock_setup.return_value = MagicMock()

                        pipeline = AnalysisPipeline(
                            api_key="test-key", model="openai/gpt-4o-mini"
                        )

        mock_setup.assert_called_once_with(
            model="openai/gpt-4o-mini", api_key="test-key"
        )
        mock_scope.assert_called_once()
        mock_incident.assert_called_once()
        mock_overview.assert_called_once()
        assert pipeline.lm is not None
        assert pipeline.source_scope is not None
        assert pipeline.incident_analysis_tool is not None
        assert pipeline.industry_overview_tool is not None

    @pytest.mark.unit
    def test_init_uses_default_model(self):
        """Test that AnalysisPipeline uses default model if not specified."""
        with patch("app.dspy_files.analysis_pipeline.setup_dspy") as mock_setup:
            with patch("app.dspy_files.analysis_pipeline.SourceScope"):
                with patch("app.dspy_files.analysis_pipeline.IncidentAnalysisModule"):
                    with patch(
                        "app.dspy_files.analysis_pipeline.IndustryOverviewModule"
                    ):
                        mock_setup.return_value = MagicMock()

                        AnalysisPipeline(api_key="test-key")

        mock_setup.assert_called_once_with(
            model="openai/gpt-4o-mini", api_key="test-key"
        )


class TestAnalysisPipelineRunClassification:
    """Tests for classification behavior in AnalysisPipeline.run()."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_classifies_unclassified_source(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that run() classifies a source that hasn't been classified."""
        # Create unclassified source
        source = create_mock_source(article_scope=None)

        # After classification, source will have scope
        classified_source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Unrelated to IUU Fishing",
                confidence=0.95,
            )
        )
        mock_source_scope.run.return_value = classified_source

        pipeline = AnalysisPipeline(api_key="test-key")
        await pipeline.run(source)

        # Verify classification was called
        mock_source_scope.run.assert_called_once_with(source=source)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_skips_classification_if_already_classified(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that run() skips classification if source already has scope."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.90,
            )
        )

        mock_incident_module.acall.return_value = {
            "parsed_data": {},
            "classification": {},
        }

        pipeline = AnalysisPipeline(api_key="test-key")
        await pipeline.run(source)

        # Verify classification was NOT called
        mock_source_scope.run.assert_not_called()


class TestAnalysisPipelineRunRouting:
    """Tests for article routing in AnalysisPipeline.run()."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_routes_unrelated_articles(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that unrelated articles return empty prediction."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Unrelated to IUU Fishing",
                confidence=0.95,
            )
        )

        pipeline = AnalysisPipeline(api_key="test-key")
        result = await pipeline.run(source)

        # Verify no analysis modules were called
        mock_incident_module.acall.assert_not_called()
        mock_overview_module.acall.assert_not_called()

        # Verify prediction structure
        assert result.sources == [source]
        assert result.extracted_data is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_routes_industry_overview_articles(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that industry overview articles are routed to overview module."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Industry Overview",
                confidence=0.88,
            )
        )

        mock_parsed_data = {"overview_key": "overview_value"}
        mock_overview_module.acall.return_value = {"parsed_data": mock_parsed_data}

        pipeline = AnalysisPipeline(api_key="test-key")
        result = await pipeline.run(source)

        # Verify correct module was called
        mock_overview_module.acall.assert_called_once_with(source=source)
        mock_incident_module.acall.assert_not_called()

        # Verify prediction structure
        assert result.sources == [source]
        assert result.parsed_data == mock_parsed_data

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_routes_multiple_incidents_articles(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that multiple incidents articles are routed to incident module."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Multiple Incidents",
                confidence=0.85,
            )
        )

        mock_incidents = [
            {"incident": "first"},
            {"incident": "second"},
        ]
        mock_incident_module.acall.return_value = {"incidents": mock_incidents}

        pipeline = AnalysisPipeline(api_key="test-key")
        result = await pipeline.run(source)

        # Verify correct module was called
        mock_incident_module.acall.assert_called_once_with(source=source)
        mock_overview_module.acall.assert_not_called()

        # Verify prediction structure
        assert result.sources == [source]
        assert result.incidents == mock_incidents

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_routes_single_incident_articles(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that single incident articles are routed to incident module."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.92,
            )
        )

        mock_parsed_data = {"vessel": "Test Vessel"}
        mock_classification = {"iuu_type": "Illegal Fishing"}
        mock_incident_module.acall.return_value = {
            "parsed_data": mock_parsed_data,
            "classification": mock_classification,
        }

        pipeline = AnalysisPipeline(api_key="test-key")
        result = await pipeline.run(source)

        # Verify correct module was called
        mock_incident_module.acall.assert_called_once_with(source=source)
        mock_overview_module.acall.assert_not_called()

        # Verify prediction structure
        assert result.sources == [source]
        assert result.parsed_data == mock_parsed_data
        assert result.incident_classification == mock_classification


class TestAnalysisPipelineErrorHandling:
    """Tests for error handling in AnalysisPipeline."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_raises_on_classification_error(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that run() raises exception on classification failure."""
        source = create_mock_source(article_scope=None)
        mock_source_scope.run.side_effect = Exception("Classification failed")

        pipeline = AnalysisPipeline(api_key="test-key")

        with pytest.raises(Exception, match="Classification failed"):
            await pipeline.run(source)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_raises_on_analysis_module_error(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that run() raises exception on analysis module failure."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.90,
            )
        )
        mock_incident_module.acall.side_effect = Exception("Analysis failed")

        pipeline = AnalysisPipeline(api_key="test-key")

        with patch("dspy.inspect_history"):  # Suppress debug logging
            with pytest.raises(Exception, match="Analysis failed"):
                await pipeline.run(source)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_handles_inspect_history_error(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test that run() handles errors when inspecting DSPy history."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.90,
            )
        )
        mock_incident_module.acall.side_effect = Exception("Analysis failed")

        pipeline = AnalysisPipeline(api_key="test-key")

        # Mock inspect_history to also fail
        with patch("dspy.inspect_history", side_effect=Exception("History error")):
            with pytest.raises(Exception, match="Analysis failed"):
                await pipeline.run(source)


class TestAnalysisPipelineEdgeCases:
    """Tests for edge cases in AnalysisPipeline."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_with_none_module_output_values(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test handling of None values in module output."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.80,
            )
        )

        # Module returns None for some values
        mock_incident_module.acall.return_value = {
            "parsed_data": None,
            "classification": None,
        }

        pipeline = AnalysisPipeline(api_key="test-key")
        result = await pipeline.run(source)

        assert result.parsed_data is None
        assert result.incident_classification is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_with_empty_incidents_list(
        self,
        mock_setup_dspy,
        mock_source_scope,
        mock_incident_module,
        mock_overview_module,
    ):
        """Test handling of empty incidents list for multiple incidents."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Multiple Incidents",
                confidence=0.75,
            )
        )

        mock_incident_module.acall.return_value = {"incidents": []}

        pipeline = AnalysisPipeline(api_key="test-key")
        result = await pipeline.run(source)

        assert result.incidents == []
