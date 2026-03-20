"""
Integration tests for service layer that require database access.

These tests use the test database to verify end-to-end service behavior
including database operations.
"""

import pytest
from unittest.mock import patch

from app.service.incident_service import IncidentService
from app.models.sources import Source
from app.models.incidents import (
    IncidentReport,
    IndustryOverview,
)
from app.dspy_files.news_analysis import PipelineResult
from tests.conftest import (
    make_source,
    make_incident,
    make_overview,
    make_pipeline_output,
)


@pytest.mark.integration
class TestIncidentServiceIntegration:
    """Integration tests for IncidentService with database."""

    @pytest.mark.asyncio
    async def test_create_report_duplicate_hash(self, test_db):
        """Test handling of duplicate article hash via DuplicateKeyError on source.insert()."""
        existing_source = make_source(
            article_text="Duplicate article text",
            url="https://example.com/original",
        )
        await existing_source.insert()

        output = make_pipeline_output(
            source=make_source(
                article_text="Duplicate article text",
                url="https://example.com/duplicate",
            ),
            incidents=[make_incident()],
        )

        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.DUPLICATE_HASHED_TEXT
        assert result.source.id == existing_source.id

    @pytest.mark.asyncio
    async def test_create_report_unrelated_content(self, test_db):
        """Test handling of unrelated content."""
        output = make_pipeline_output(
            source=make_source(
                article_text="This article is about gardening, not fishing.",
                url="https://example.com/gardening",
            ),
            status=PipelineResult.UNRELATED_CONTENT,
        )

        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.UNRELATED_CONTENT
        assert result.source.id is not None
        assert len(result.incidents) == 0

    @pytest.mark.asyncio
    async def test_create_report_with_incident(self, test_db):
        """Test report creation with incident data."""
        output = make_pipeline_output(
            source=make_source(
                article_text="Test article about illegal fishing incident",
                url="https://example.com/incident",
            ),
            incidents=[make_incident()],
        )

        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.SUCCESS
        assert result.source.id is not None
        assert len(result.incidents) == 1
        assert result.incidents[0].id is not None
        refreshed_incident = await IncidentReport.get(result.incidents[0].id)
        assert refreshed_incident.primary_source is not None

    @pytest.mark.asyncio
    async def test_update_report_with_db(self, test_db, sample_incident):
        """Test updating an incident report with real database."""
        update_data = {"status": "modified"}

        result = await IncidentService.update_report(
            str(sample_incident.id), update_data
        )

        assert result.status == "modified"
        refreshed = await IncidentReport.get(sample_incident.id)
        assert refreshed.status == "modified"

    @pytest.mark.asyncio
    async def test_delete_report_with_db(self, test_db, sample_incident):
        """Test deleting an incident report with real database."""
        incident_id = sample_incident.id

        result = await IncidentService.delete_report(str(incident_id))

        assert result is True
        deleted = await IncidentReport.get(incident_id)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_create_report_with_overview_links_source(self, test_db):
        """Test that a successfully created industry overview has its source linked."""
        output = make_pipeline_output(
            source=make_source(
                article_text="Industry overview about IUU fishing trends in Pacific.",
                url="https://example.com/overview",
            ),
            industry_overview=make_overview(),
        )

        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.SUCCESS
        assert result.source.id is not None
        saved_overview = await IndustryOverview.get(output.industry_overview.id)
        assert saved_overview is not None
        assert saved_overview.source is not None
        source_ref_id = (
            saved_overview.source.ref.id
            if hasattr(saved_overview.source, "ref")
            else saved_overview.source.id
        )
        assert source_ref_id == result.source.id

    @pytest.mark.asyncio
    async def test_create_report_duplicate_hash_with_overview(self, test_db):
        """Test that a duplicate-hash race links the overview to the existing source."""
        existing_source = make_source(
            article_text="Industry overview duplicate race condition text.",
            url="https://example.com/overview-original",
        )
        await existing_source.insert()

        overview = make_overview()

        output = make_pipeline_output(
            source=make_source(
                article_text="Industry overview duplicate race condition text.",
                url="https://example.com/overview-duplicate",
            ),
            industry_overview=overview,
        )

        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.DUPLICATE_HASHED_TEXT
        assert result.source.id == existing_source.id
        saved_overview = await IndustryOverview.get(overview.id)
        assert saved_overview is not None
        assert saved_overview.source is not None
        source_ref_id = (
            saved_overview.source.ref.id
            if hasattr(saved_overview.source, "ref")
            else saved_overview.source.id
        )
        assert source_ref_id == existing_source.id

    @pytest.mark.asyncio
    async def test_create_report_duplicate_hash_cleans_up_incidents(self, test_db):
        """Test that orphaned incidents are deleted when a duplicate hash race occurs."""
        existing_source = make_source(
            article_text="Incident duplicate race condition text.",
            url="https://example.com/incident-original",
        )
        await existing_source.insert()

        incident = make_incident()

        output = make_pipeline_output(
            source=make_source(
                article_text="Incident duplicate race condition text.",
                url="https://example.com/incident-duplicate",
            ),
            incidents=[incident],
        )

        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.DUPLICATE_HASHED_TEXT
        assert result.source.id == existing_source.id
        deleted_incident = await IncidentReport.get(incident.id)
        assert deleted_incident is None

    @pytest.mark.asyncio
    async def test_create_report_source_failure_cleans_up_orphans(self, test_db):
        """Test that orphaned incidents and overviews are deleted when source.insert fails."""
        incident = make_incident()
        overview = make_overview()

        output = make_pipeline_output(
            source=make_source(
                article_text="Source failure cleanup test text.",
                url="https://example.com/source-failure",
            ),
            incidents=[incident],
            industry_overview=overview,
        )

        async def failing_source_insert(self_):
            raise RuntimeError("DB connection lost")

        with patch.object(Source, "insert", failing_source_insert):
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await IncidentService._create_report(output)

        assert await IncidentReport.get(incident.id) is None
        assert await IndustryOverview.get(overview.id) is None
