"""
Unit tests for service layer (IncidentService, SourceService, OverviewService).

These tests mock external dependencies (DSPy, database operations) to test
service logic in isolation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.service.incident_service import IncidentService
from app.service.source_service import SourceService
from app.service.overview_service import OverviewService
from app.models.sources import Source
from app.models.incidents import (
    IncidentReport,
    IndustryOverview,
    ExtractedIncidentData,
    VesselData,
    EventData,
    IncidentClassification,
    IllegalFishingClassification,
    Species,
)
from app.dspy_files.news_analysis import PipelineOutput, PipelineResult
from pymongo.errors import DuplicateKeyError


@pytest.mark.unit
class TestIncidentService:
    """Tests for IncidentService."""

    @pytest.mark.asyncio
    async def test_get_orchestrator(self):
        """Test that _get_orchestrator creates an AnalysisOrchestrator."""
        with patch("app.service.incident_service.AnalysisOrchestrator") as mock_orch:
            mock_instance = MagicMock()
            mock_orch.return_value = mock_instance

            orchestrator = IncidentService._get_orchestrator()

            mock_orch.assert_called_once()
            assert orchestrator == mock_instance

    @pytest.mark.asyncio
    async def test_create_report_from_url_success(self, test_db):
        """Test successful report creation from URL."""
        url = "https://example.com/test-article"

        # Mock the orchestrator and its methods
        with patch.object(
            IncidentService, "_get_orchestrator"
        ) as mock_get_orch, patch.object(
            IncidentService, "_create_report"
        ) as mock_create:
            # Setup mocks
            mock_orchestrator = AsyncMock()
            mock_get_orch.return_value = mock_orchestrator

            # Create a mock pipeline output
            mock_source = Source(
                article_text="Test article about illegal fishing",
                url=url,
            )
            mock_output = PipelineOutput(
                source=mock_source,
                status=PipelineResult.SUCCESS,
                incidents=[],
                industry_overview=None,
            )

            mock_orchestrator.run_full_analysis_from_url = AsyncMock(
                return_value=mock_output
            )
            mock_create.return_value = mock_output

            # Execute
            result = await IncidentService.create_report_from_url(url)

            # Verify
            mock_get_orch.assert_called_once()
            mock_orchestrator.run_full_analysis_from_url.assert_called_once_with(
                url=url
            )
            mock_create.assert_called_once_with(mock_output)
            assert result == mock_output

    @pytest.mark.asyncio
    async def test_create_report_from_text(self, test_db):
        """Test report creation from text input."""
        text = "Test article text about illegal fishing operations."
        title = "Test Title"
        author = "Test Author"

        with patch.object(
            IncidentService, "_get_orchestrator"
        ) as mock_get_orch, patch.object(
            IncidentService, "_create_report"
        ) as mock_create:
            # Setup mocks
            mock_orchestrator = AsyncMock()
            mock_get_orch.return_value = mock_orchestrator

            mock_source = Source(article_text=text, article_title=title, author=author)
            mock_output = PipelineOutput(
                source=mock_source,
                status=PipelineResult.SUCCESS,
                incidents=[],
                industry_overview=None,
            )

            mock_orchestrator.run_full_analysis_from_text = AsyncMock(
                return_value=mock_output
            )
            mock_create.return_value = mock_output

            # Execute
            result = await IncidentService.create_report_from_text(
                text=text, title=title, author=author
            )

            # Verify
            mock_orchestrator.run_full_analysis_from_text.assert_called_once()
            call_kwargs = (
                mock_orchestrator.run_full_analysis_from_text.call_args.kwargs
            )
            assert call_kwargs["text"] == text
            assert call_kwargs["title"] == title
            assert call_kwargs["author"] == author
            assert result == mock_output

    @pytest.mark.asyncio
    async def test_create_report_duplicate_hash(self, test_db):
        """Test handling of duplicate article hash."""
        # Create a source
        existing_source = Source(
            article_text="Duplicate article text",
            url="https://example.com/original",
        )
        await existing_source.insert()

        # Create output with same text hash
        new_source = Source(
            article_text="Duplicate article text",
            url="https://example.com/duplicate",
        )

        output = PipelineOutput(
            source=new_source,
            status=PipelineResult.SUCCESS,
            incidents=[],
            industry_overview=None,
        )

        # Execute
        result = await IncidentService._create_report(output)

        # Verify - should detect duplicate and return existing source
        assert result.status == PipelineResult.DUPLICATE_HASHED_TEXT
        assert result.source.id == existing_source.id

    @pytest.mark.asyncio
    async def test_create_report_unrelated_content(self, test_db):
        """Test handling of unrelated content."""
        source = Source(
            article_text="This article is about gardening, not fishing.",
            url="https://example.com/gardening",
        )

        output = PipelineOutput(
            source=source,
            status=PipelineResult.UNRELATED_CONTENT,
            incidents=[],
            industry_overview=None,
        )

        # Execute
        result = await IncidentService._create_report(output)

        # Verify - source should be saved but no incidents
        assert result.status == PipelineResult.UNRELATED_CONTENT
        assert result.source.id is not None  # Source was saved
        assert len(result.incidents) == 0

    @pytest.mark.asyncio
    async def test_create_report_with_incident(self, test_db):
        """Test report creation with incident data."""
        source = Source(
            article_text="Test article about illegal fishing incident",
            url="https://example.com/incident",
        )

        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Test Vessel"),
                eventData=EventData(
                    eventDate="2024-01-15",
                    eventLocation="Pacific Ocean",
                    resolution="Vessel detained",
                ),
                speciesInvolved=[Species(speciesCommonName="Tuna")],
                productsInvolved=[],
                description="Test incident",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUSubType=["Invalid or no permit or license"],
                        IUUTypeReason="No valid license",
                    )
                ]
            ),
        )

        output = PipelineOutput(
            source=source,
            status=PipelineResult.SUCCESS,
            incidents=[incident],
            industry_overview=None,
        )

        # Execute
        result = await IncidentService._create_report(output)

        # Verify
        assert result.status == PipelineResult.SUCCESS
        assert result.source.id is not None
        assert len(result.incidents) == 1
        assert result.incidents[0].id is not None
        # Verify relationship was established
        refreshed_incident = await IncidentReport.get(result.incidents[0].id)
        assert refreshed_incident.primary_source is not None

    @pytest.mark.asyncio
    async def test_update_report(self, test_db, sample_incident):
        """Test updating an incident report."""
        update_data = {"status": "modified", "verified": True}

        # Mock the Service.update_model method
        with patch(
            "app.service.service.Service.update_model"
        ) as mock_update:
            mock_update.return_value = sample_incident

            result = await IncidentService.update_report(
                str(sample_incident.id), update_data
            )

            mock_update.assert_called_once_with(
                model_cls=IncidentReport,
                model_id=str(sample_incident.id),
                update_data=update_data,
                model_name="report",
            )

    @pytest.mark.asyncio
    async def test_delete_report(self, test_db, sample_incident):
        """Test deleting an incident report."""
        # Mock the Service.delete method
        with patch("app.service.service.Service.delete") as mock_delete:
            mock_delete.return_value = True

            result = await IncidentService.delete_report(str(sample_incident.id))

            mock_delete.assert_called_once_with(
                model_cls=IncidentReport,
                model_id=str(sample_incident.id),
                model_name="report",
            )
            assert result is True


@pytest.mark.unit
class TestSourceService:
    """Tests for SourceService."""

    @pytest.mark.asyncio
    async def test_update_source(self, test_db, sample_source):
        """Test updating a source."""
        update_data = {"status": "modified", "verified": True}

        with patch("app.service.service.Service.update_model") as mock_update:
            mock_update.return_value = sample_source

            result = await SourceService.update_source(
                str(sample_source.id), update_data
            )

            mock_update.assert_called_once_with(
                model_cls=Source,
                model_id=str(sample_source.id),
                update_data=update_data,
                model_name="source",
            )

    @pytest.mark.asyncio
    async def test_delete_source(self, test_db, sample_source):
        """Test deleting a source."""
        with patch("app.service.service.Service.delete") as mock_delete:
            mock_delete.return_value = True

            result = await SourceService.delete_source(str(sample_source.id))

            mock_delete.assert_called_once_with(
                model_cls=Source,
                model_id=str(sample_source.id),
                model_name="source",
            )
            assert result is True


@pytest.mark.unit
class TestOverviewService:
    """Tests for OverviewService."""

    @pytest.mark.asyncio
    async def test_update_overview(self, test_db):
        """Test updating an industry overview."""
        # Create a sample overview
        from app.models.incidents import IndustryOverviewExtract

        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[Species(speciesCommonName="Tuna")],
                countries=["Japan"],
                companies=["Test Corp"],
                incidents=[],
                summary="Test overview",
            )
        )
        await overview.insert()

        update_data = {"status": "modified", "verified": True}

        with patch("app.service.service.Service.update_model") as mock_update:
            mock_update.return_value = overview

            result = await OverviewService.update_overview(
                str(overview.id), update_data
            )

            mock_update.assert_called_once_with(
                model_cls=IndustryOverview,
                model_id=str(overview.id),
                update_data=update_data,
                model_name="overview",
            )

    @pytest.mark.asyncio
    async def test_delete_overview(self, test_db):
        """Test deleting an industry overview."""
        from app.models.incidents import IndustryOverviewExtract

        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[Species(speciesCommonName="Tuna")],
                countries=["Japan"],
                companies=["Test Corp"],
                incidents=[],
                summary="Test overview",
            )
        )
        await overview.insert()

        with patch("app.service.service.Service.delete") as mock_delete:
            mock_delete.return_value = True

            result = await OverviewService.delete_overview(str(overview.id))

            mock_delete.assert_called_once_with(
                model_cls=IndustryOverview,
                model_id=str(overview.id),
                model_name="overview",
            )
            assert result is True
