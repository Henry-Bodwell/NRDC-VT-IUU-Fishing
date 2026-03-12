"""
Integration tests for service layer that require database access.

These tests use the test database to verify end-to-end service behavior
including database operations.
"""

import pytest
from unittest.mock import patch, AsyncMock

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
    IndustryOverview,
    IndustryOverviewExtract,
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

    @pytest.mark.asyncio
    async def test_create_report_with_overview_links_source(self, test_db):
        """Test that a successfully created industry overview has its source linked."""
        source = Source(
            article_text="Industry overview about IUU fishing trends in Pacific.",
            url="https://example.com/overview",
        )
        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[],
                countries=["Pacific"],
                companies=[],
                incidents=[],
                summary="Overview of IUU trends.",
            )
        )

        output = PipelineOutput(
            source=source,
            status=PipelineResult.SUCCESS,
            incidents=[],
            industry_overview=overview,
        )

        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.SUCCESS
        assert result.source.id is not None
        # Verify the overview has the source linked
        saved_overview = await IndustryOverview.get(overview.id, fetch_links=True)
        assert saved_overview is not None
        assert saved_overview.source is not None
        assert saved_overview.source.id == result.source.id

    @pytest.mark.asyncio
    async def test_create_report_duplicate_hash_with_overview(self, test_db):
        """Test that a duplicate-hash race links the overview to the existing source."""
        # Insert existing source with the same article text
        existing_source = Source(
            article_text="Industry overview duplicate race condition text.",
            url="https://example.com/overview-original",
        )
        await existing_source.insert()

        # New source with identical text (same hash) but different URL
        new_source = Source(
            article_text="Industry overview duplicate race condition text.",
            url="https://example.com/overview-duplicate",
        )
        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[],
                countries=[],
                companies=[],
                incidents=[],
                summary="Duplicate race overview.",
            )
        )
        await overview.insert()  # Already saved (as the service does before source)

        output = PipelineOutput(
            source=new_source,
            status=PipelineResult.SUCCESS,
            incidents=[],
            industry_overview=overview,
        )

        result = await IncidentService._create_report(output)

        # Should detect duplicate and return existing source
        assert result.status == PipelineResult.DUPLICATE_HASHED_TEXT
        assert result.source.id == existing_source.id
        # Overview must be linked to the existing source
        saved_overview = await IndustryOverview.get(overview.id, fetch_links=True)
        assert saved_overview is not None
        assert saved_overview.source is not None
        assert saved_overview.source.id == existing_source.id

    @pytest.mark.asyncio
    async def test_create_report_duplicate_hash_cleans_up_incidents(self, test_db):
        """Test that orphaned incidents are deleted when a duplicate hash race occurs."""
        existing_source = Source(
            article_text="Incident duplicate race condition text.",
            url="https://example.com/incident-original",
        )
        await existing_source.insert()

        new_source = Source(
            article_text="Incident duplicate race condition text.",
            url="https://example.com/incident-duplicate",
        )
        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Race Vessel"),
                eventData=EventData(
                    eventDate="2024-03-01",
                    eventLocation="Atlantic",
                    resolution="Detained",
                ),
                speciesInvolved=[],
                productsInvolved=[],
                description="Orphan incident from race.",
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
        await incident.insert()  # Already saved (as the service does before source)
        incident_id = incident.id

        output = PipelineOutput(
            source=new_source,
            status=PipelineResult.SUCCESS,
            incidents=[incident],
            industry_overview=None,
        )

        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.DUPLICATE_HASHED_TEXT
        assert result.source.id == existing_source.id
        # Orphan incident must have been deleted
        deleted_incident = await IncidentReport.get(incident_id)
        assert deleted_incident is None

    @pytest.mark.asyncio
    async def test_create_report_source_failure_cleans_up_orphans(self, test_db):
        """Test that orphaned incidents and overviews are deleted when source.insert fails."""
        source = Source(
            article_text="Source failure cleanup test text.",
            url="https://example.com/source-failure",
        )
        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Orphan Vessel"),
                eventData=EventData(
                    eventDate="2024-04-01",
                    eventLocation="Indian Ocean",
                    resolution="None",
                ),
                speciesInvolved=[],
                productsInvolved=[],
                description="Orphan from source failure.",
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
        await incident.insert()
        incident_id = incident.id

        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[],
                countries=[],
                companies=[],
                incidents=[],
                summary="Orphan overview from source failure.",
            )
        )
        await overview.insert()
        overview_id = overview.id

        output = PipelineOutput(
            source=source,
            status=PipelineResult.SUCCESS,
            incidents=[incident],
            industry_overview=overview,
        )

        # Simulate source.insert() raising a non-duplicate error
        with patch.object(
            Source, "insert", AsyncMock(side_effect=RuntimeError("DB connection lost"))
        ):
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await IncidentService._create_report(output)

        # Both orphans must have been cleaned up
        assert await IncidentReport.get(incident_id) is None
        assert await IndustryOverview.get(overview_id) is None
