"""
Integration tests for service layer that require database access.

These tests use the test database to verify end-to-end service behavior
including database operations.
"""

import pytest

from app.service.incident_service import IncidentService
from app.models.sources import Source
from app.models.incidents import (
    IncidentReport,
    ExtractedIncidentData,
    VesselData,
    EventData,
    IncidentClassification,
    IllegalFishingClassification,
    Species,
)
from app.dspy_files.news_analysis import PipelineOutput, PipelineResult


@pytest.mark.integration
class TestIncidentServiceIntegration:
    """Integration tests for IncidentService with database."""

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
    async def test_update_report_with_db(self, test_db, sample_incident):
        """Test updating an incident report with real database."""
        update_data = {"status": "modified"}

        # Update via service
        result = await IncidentService.update_report(
            str(sample_incident.id), update_data
        )

        # Verify update persisted
        assert result.status == "modified"
        refreshed = await IncidentReport.get(sample_incident.id)
        assert refreshed.status == "modified"

    @pytest.mark.asyncio
    async def test_delete_report_with_db(self, test_db, sample_incident):
        """Test deleting an incident report with real database."""
        incident_id = sample_incident.id

        # Delete via service
        result = await IncidentService.delete_report(str(incident_id))

        # Verify deletion
        assert result is True
        deleted = await IncidentReport.get(incident_id)
        assert deleted is None
