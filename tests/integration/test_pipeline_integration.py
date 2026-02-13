"""
Integration tests for the full analysis pipeline (URL/PDF/text to incident).

These tests verify the end-to-end flow with real MongoDB but mocked LLM calls.
Tests cover:
- Full pipeline from various input types to database persistence
- Source-incident relationship integrity
- Audit trail creation
- Task tracking integration
- Error handling scenarios
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.service.incident_service import IncidentService
from app.models.sources import Source, ArticleScopeClassification
from app.models.incidents import (
    IncidentReport,
    IndustryOverview,
    IndustryOverviewExtract,
    ExtractedIncidentData,
    VesselData,
    EventData,
    IncidentClassification,
    IllegalFishingClassification,
    Species,
)
from app.models.task import TaskStatus
from app.audit.context import AuditContext
from app.dspy_files.news_analysis import (
    PipelineOutput,
    PipelineResult,
)


def create_test_source(
    text: str = "Test article about illegal fishing incident.",
    url: str = "https://example.com/test",
    **kwargs,
) -> Source:
    """Create a test Source object."""
    defaults = {
        "article_text": text,
        "url": url,
        "article_title": "Test Article",
        "author": "Test Author",
        "publisher": "Test Publisher",
        "input_category": "text_upload",
        "status": "user_input",
    }
    defaults.update(kwargs)
    return Source(**defaults)


def create_test_incident(source: Source = None) -> IncidentReport:
    """Create a test IncidentReport."""
    return IncidentReport(
        extracted_information=ExtractedIncidentData(
            vesselInformation=VesselData(
                vesselName="Thunder",
                vesselFlag="Nigeria",
                imoNumber="123456",
            ),
            eventData=EventData(
                eventDate="2024-03-15",
                eventLocation="Southern Ocean",
                resolution="Vessel sunk after chase",
            ),
            speciesInvolved=[Species(speciesCommonName="Patagonian Toothfish")],
            productsInvolved=[],
            description="Illegal fishing vessel Thunder was caught operating in protected waters.",
        ),
        incident_classification=IncidentClassification(
            iuuClassifications=[
                IllegalFishingClassification(
                    IUUSubType=["Fishing in closed areas or closed seasons"],
                    IUUTypeReason="Operated in protected marine reserve",
                )
            ]
        ),
        status="extracted",
    )


def create_test_industry_overview() -> IndustryOverview:
    """Create a test IndustryOverview."""
    return IndustryOverview(
        extracted_information=IndustryOverviewExtract(
            species=[Species(speciesCommonName="Tuna")],
            countries=["China", "Japan"],
            companies=["Fishing Corp"],
            incidents=[],
            summary="Overview of illegal fishing trends in the Pacific region.",
        )
    )


def create_success_output(
    source: Source,
    incidents: list = None,
    overview: IndustryOverview = None,
) -> PipelineOutput:
    """Create a successful pipeline output."""
    return PipelineOutput(
        status=PipelineResult.SUCCESS,
        source=source,
        incidents=incidents or [],
        industry_overview=overview,
    )


@pytest.fixture
def mock_orchestrator_single_incident():
    """Mock orchestrator to return a single incident."""
    with patch.object(IncidentService, "_get_orchestrator") as mock_get:
        mock_orch = MagicMock()

        async def mock_analysis_from_text(**kwargs):
            text = kwargs.get("text", "")
            source = create_test_source(
                text=text,
                url=kwargs.get("url", ""),
                author=kwargs.get("author", ""),
                article_title=kwargs.get("title", ""),
                publisher=kwargs.get("publisher", ""),
                status=kwargs.get("status", "user_input"),
            )
            source.article_scope = ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.95,
            )
            incident = create_test_incident()
            return create_success_output(source, incidents=[incident])

        async def mock_analysis_from_url(url, **kwargs):
            source = create_test_source(
                text="Article text extracted from URL about illegal fishing.",
                url=url,
                input_category="url",
            )
            source.article_scope = ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.95,
            )
            incident = create_test_incident()
            return create_success_output(source, incidents=[incident])

        mock_orch.run_full_analysis_from_text = AsyncMock(
            side_effect=mock_analysis_from_text
        )
        mock_orch.run_full_analysis_from_url = AsyncMock(
            side_effect=mock_analysis_from_url
        )
        mock_get.return_value = mock_orch
        yield mock_orch


@pytest.fixture
def mock_orchestrator_multiple_incidents():
    """Mock orchestrator to return multiple incidents."""
    with patch.object(IncidentService, "_get_orchestrator") as mock_get:
        mock_orch = MagicMock()

        async def mock_analysis(**kwargs):
            text = kwargs.get("text", "")
            source = create_test_source(text=text)
            source.article_scope = ArticleScopeClassification(
                articleType="Multiple Incidents",
                confidence=0.90,
            )

            # Create two different incidents
            incident1 = IncidentReport(
                extracted_information=ExtractedIncidentData(
                    vesselInformation=VesselData(
                        vesselName="Vessel A", vesselFlag="China"
                    ),
                    eventData=EventData(
                        eventDate="2024-01-10",
                        eventLocation="Pacific Ocean",
                        resolution="Fined",
                    ),
                    speciesInvolved=[Species(speciesCommonName="Tuna")],
                    productsInvolved=[],
                    description="First incident",
                ),
                incident_classification=IncidentClassification(
                    iuuClassifications=[
                        IllegalFishingClassification(
                            IUUSubType=["Invalid or no permit or license"],
                            IUUTypeReason="No license",
                        )
                    ]
                ),
                status="extracted",
            )

            incident2 = IncidentReport(
                extracted_information=ExtractedIncidentData(
                    vesselInformation=VesselData(
                        vesselName="Vessel B", vesselFlag="Taiwan"
                    ),
                    eventData=EventData(
                        eventDate="2024-01-12",
                        eventLocation="Indian Ocean",
                        resolution="Released with warning",
                    ),
                    speciesInvolved=[Species(speciesCommonName="Shark")],
                    productsInvolved=[],
                    description="Second incident",
                ),
                incident_classification=IncidentClassification(
                    iuuClassifications=[
                        IllegalFishingClassification(
                            IUUSubType=["Exceeding catch quotas"],
                            IUUTypeReason="Exceeded quota by 50%",
                        )
                    ]
                ),
                status="extracted",
            )

            return create_success_output(source, incidents=[incident1, incident2])

        mock_orch.run_full_analysis_from_text = AsyncMock(side_effect=mock_analysis)
        mock_get.return_value = mock_orch
        yield mock_orch


@pytest.fixture
def mock_orchestrator_industry_overview():
    """Mock orchestrator to return an industry overview."""
    with patch.object(IncidentService, "_get_orchestrator") as mock_get:
        mock_orch = MagicMock()

        async def mock_analysis(**kwargs):
            text = kwargs.get("text", "")
            source = create_test_source(text=text)
            source.article_scope = ArticleScopeClassification(
                articleType="Industry Overview",
                confidence=0.85,
            )
            overview = create_test_industry_overview()
            return create_success_output(source, overview=overview)

        mock_orch.run_full_analysis_from_text = AsyncMock(side_effect=mock_analysis)
        mock_get.return_value = mock_orch
        yield mock_orch


@pytest.fixture
def mock_orchestrator_unrelated():
    """Mock orchestrator to return unrelated content."""
    with patch.object(IncidentService, "_get_orchestrator") as mock_get:
        mock_orch = MagicMock()

        async def mock_analysis(**kwargs):
            text = kwargs.get("text", "")
            source = create_test_source(text=text)
            source.article_scope = ArticleScopeClassification(
                articleType="Unrelated to IUU Fishing",
                confidence=0.99,
            )
            return PipelineOutput(
                status=PipelineResult.UNRELATED_CONTENT,
                source=source,
                incidents=[],
            )

        mock_orch.run_full_analysis_from_text = AsyncMock(side_effect=mock_analysis)
        mock_get.return_value = mock_orch
        yield mock_orch


@pytest.mark.integration
class TestFullPipelineIntegration:
    """Integration tests for the complete analysis pipeline."""

    @pytest.mark.asyncio
    async def test_create_report_from_text_single_incident(
        self, test_db, mock_orchestrator_single_incident
    ):
        """Test full pipeline from text input to single incident creation."""
        text = (
            "A fishing vessel named Thunder was caught illegally fishing "
            "in the Southern Ocean on March 15, 2024. The vessel, flagged to Nigeria, "
            "was operating without permits in a protected marine reserve."
        )

        # Execute pipeline
        result = await IncidentService.create_report_from_text(
            text=text,
            url="https://example.com/thunder-article",
            author="Maritime Reporter",
            title="Thunder Caught",
            publisher="Ocean News",
        )

        # Verify success
        assert result.status == PipelineResult.SUCCESS
        assert result.source is not None
        assert result.source.id is not None
        assert len(result.incidents) == 1

        # Verify source was saved to database
        saved_source = await Source.get(result.source.id)
        assert saved_source is not None
        assert saved_source.article_scope.articleType == "Single Incident"

        # Verify incident was saved
        saved_incident = await IncidentReport.get(result.incidents[0].id)
        assert saved_incident is not None
        assert (
            saved_incident.extracted_information.vesselInformation.vesselName
            == "Thunder"
        )

        # Verify source-incident relationship
        assert saved_incident.primary_source is not None
        assert saved_incident.primary_source.ref.id == saved_source.id

    @pytest.mark.asyncio
    async def test_create_report_from_text_multiple_incidents(
        self, test_db, mock_orchestrator_multiple_incidents
    ):
        """Test pipeline creates multiple incidents from a single source."""
        text = (
            "Two fishing vessels were caught this week. Vessel A from China was fined "
            "for operating without a license in the Pacific. Vessel B from Taiwan was "
            "caught exceeding catch quotas in the Indian Ocean."
        )

        result = await IncidentService.create_report_from_text(text=text)

        # Verify success with multiple incidents
        assert result.status == PipelineResult.SUCCESS
        assert result.source is not None
        assert len(result.incidents) == 2

        # Verify all incidents saved
        for incident in result.incidents:
            saved = await IncidentReport.get(incident.id)
            assert saved is not None
            # Each incident should link to the same source
            assert saved.primary_source is not None

        # Verify different vessel names
        vessel_names = [
            i.extracted_information.vesselInformation.vesselName
            for i in result.incidents
        ]
        assert "Vessel A" in vessel_names
        assert "Vessel B" in vessel_names

    @pytest.mark.asyncio
    async def test_create_report_from_text_industry_overview(
        self, test_db, mock_orchestrator_industry_overview
    ):
        """Test pipeline creates industry overview instead of incidents."""
        text = (
            "IUU fishing trends in 2024 show increased surveillance efforts across "
            "the Pacific region. New regulations have been proposed to combat illegal "
            "fishing in the South China Sea. This overview examines key developments."
        )

        result = await IncidentService.create_report_from_text(text=text)

        # Verify success with overview (not incidents)
        assert result.status == PipelineResult.SUCCESS
        assert result.source is not None
        assert len(result.incidents) == 0
        assert result.industry_overview is not None

        # Verify overview was saved
        saved_overview = await IndustryOverview.get(result.industry_overview.id)
        assert saved_overview is not None
        assert (
            "illegal fishing trends"
            in saved_overview.extracted_information.summary.lower()
        )

    @pytest.mark.asyncio
    async def test_create_report_from_text_unrelated_content(
        self, test_db, mock_orchestrator_unrelated
    ):
        """Test pipeline handles unrelated content correctly."""
        text = (
            "This article is about gardening tips for spring. Plant your tomatoes "
            "in March and water them regularly. Nothing to do with fishing at all."
        )

        result = await IncidentService.create_report_from_text(text=text)

        # Verify unrelated status
        assert result.status == PipelineResult.UNRELATED_CONTENT
        assert result.source is not None
        assert result.source.id is not None  # Source still saved
        assert len(result.incidents) == 0
        assert result.industry_overview is None

        # Source should be in database with unrelated classification
        saved_source = await Source.get(result.source.id)
        assert saved_source is not None
        assert saved_source.article_scope.articleType == "Unrelated to IUU Fishing"

    @pytest.mark.asyncio
    async def test_create_report_from_url(
        self, test_db, mock_orchestrator_single_incident
    ):
        """Test full pipeline from URL to incident creation."""
        url = "https://maritime-news.com/thunder-incident"

        result = await IncidentService.create_report_from_url(url=url)

        # Verify success
        assert result.status == PipelineResult.SUCCESS
        assert result.source is not None
        assert result.source.url == url
        assert len(result.incidents) == 1

        # Verify mock was called
        mock_orchestrator_single_incident.run_full_analysis_from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_report_duplicate_detection(
        self, test_db, mock_orchestrator_single_incident
    ):
        """Test that duplicate articles are detected by hash."""
        text = "Unique article text for duplicate detection test purposes here."

        # First submission
        result1 = await IncidentService.create_report_from_text(text=text)
        assert result1.status == PipelineResult.SUCCESS
        first_source_id = result1.source.id

        # Second submission with same text - mock returns duplicate status
        with patch.object(IncidentService, "_get_orchestrator") as mock_get:
            mock_orch = MagicMock()

            async def mock_duplicate(**kwargs):
                # Find the existing source
                existing = await Source.find_one(
                    Source.article_hash == result1.source.article_hash
                )
                return PipelineOutput(
                    status=PipelineResult.DUPLICATE_HASHED_TEXT,
                    source=existing,
                    incidents=[],
                    error_message="Duplicate Article",
                )

            mock_orch.run_full_analysis_from_text = AsyncMock(
                side_effect=mock_duplicate
            )
            mock_get.return_value = mock_orch

            result2 = await IncidentService.create_report_from_text(text=text)

        assert result2.status == PipelineResult.DUPLICATE_HASHED_TEXT
        assert result2.source.id == first_source_id

        # Only one source should exist with this hash
        sources = await Source.find(
            Source.article_hash == result1.source.article_hash
        ).to_list()
        assert len(sources) == 1

    @pytest.mark.asyncio
    async def test_create_report_text_too_short(self, test_db):
        """Test that short text is rejected."""
        result = await IncidentService.create_report_from_text(text="Too short")

        assert result.status == PipelineResult.INVALID_INPUT
        assert "too short" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_source_incident_bidirectional_relationship(
        self, test_db, mock_orchestrator_single_incident
    ):
        """Test that source-incident relationships are properly bidirectional."""
        text = (
            "Test article for relationship verification. A vessel was caught fishing "
            "illegally in restricted waters on January 1, 2024."
        )

        result = await IncidentService.create_report_from_text(text=text)

        # Get fresh copies from database
        source = await Source.get(result.source.id)
        incident = await IncidentReport.get(result.incidents[0].id)

        # Verify incident has primary_source pointing to source
        assert incident.primary_source is not None
        assert incident.primary_source.ref.id == source.id

        # Verify source.incidents contains the incident
        assert source.incidents is not None
        assert len(source.incidents) > 0


@pytest.mark.integration
class TestPipelineAuditTrail:
    """Tests for audit trail creation during pipeline execution."""

    @pytest.mark.asyncio
    async def test_audit_context_sets_created_by(
        self, test_db, mock_orchestrator_single_incident
    ):
        """Test that audit context sets created_by on saved documents."""
        text = (
            "Audit test article. A vessel named Auditor was caught fishing illegally "
            "in the Atlantic Ocean on February 20, 2024."
        )

        test_user_id = "test-audit-user-123"

        # Execute with audit context
        with AuditContext.with_user(test_user_id):
            result = await IncidentService.create_report_from_text(text=text)

        assert result.status == PipelineResult.SUCCESS
        assert len(result.incidents) == 1

        # Verify created_by is set on incident
        incident = await IncidentReport.get(result.incidents[0].id)
        assert incident.created_by == test_user_id


@pytest.mark.integration
class TestPipelineTaskTracking:
    """Tests for task tracking during pipeline execution."""

    @pytest.mark.asyncio
    async def test_task_tracking_successful_completion(
        self, test_db, mock_orchestrator_single_incident
    ):
        """Test that task status is updated through pipeline execution."""
        # Create a task
        task = TaskStatus(
            task_type="incident_analysis",
            user_id="test-user",
            input_params={"text": "Test input"},
        )
        await task.insert()

        text = (
            "Task tracking test. A vessel was caught in illegal fishing activity "
            "near the coast on March 1, 2024. Details are being investigated."
        )

        # Run analysis with task tracking
        await IncidentService.run_analysis_with_task_tracking(
            task_id=task.task_id,
            input_type="text",
            text=text,
        )

        # Verify task was updated
        updated_task = await TaskStatus.find_one(TaskStatus.task_id == task.task_id)
        assert updated_task.status == "completed"
        assert updated_task.progress["percent"] == 100
        assert updated_task.result is not None
        assert updated_task.result["status"] == PipelineResult.SUCCESS.value

    @pytest.mark.asyncio
    async def test_task_tracking_failure(self, test_db):
        """Test that task is marked failed on pipeline error."""
        # Create a task
        task = TaskStatus(
            task_type="incident_analysis",
            user_id="test-user",
        )
        await task.insert()

        # Mock pipeline to raise an exception
        with patch.object(IncidentService, "_get_orchestrator") as mock_get_orch:
            mock_orchestrator = MagicMock()
            mock_orchestrator.run_full_analysis_from_text = AsyncMock(
                side_effect=Exception("LLM API Error")
            )
            mock_get_orch.return_value = mock_orchestrator

            # Should not raise, but mark task as failed
            with pytest.raises(Exception):
                await IncidentService.run_analysis_with_task_tracking(
                    task_id=task.task_id,
                    input_type="text",
                    text="Some text that will fail during processing test.",
                )

        # Verify task was marked as failed
        updated_task = await TaskStatus.find_one(TaskStatus.task_id == task.task_id)
        assert updated_task.status == "failed"
        assert "LLM API Error" in updated_task.error

    @pytest.mark.asyncio
    async def test_task_tracking_unrelated_content(
        self, test_db, mock_orchestrator_unrelated
    ):
        """Test that unrelated content still marks task as completed."""
        task = TaskStatus(
            task_type="incident_analysis",
            user_id="test-user",
        )
        await task.insert()

        text = (
            "This is an article about cooking recipes. It has nothing to do with "
            "fishing or maritime activities whatsoever. Great pasta tips inside."
        )

        await IncidentService.run_analysis_with_task_tracking(
            task_id=task.task_id,
            input_type="text",
            text=text,
        )

        # Unrelated content should still complete (not fail)
        updated_task = await TaskStatus.find_one(TaskStatus.task_id == task.task_id)
        assert updated_task.status == "completed"
        assert updated_task.result["status"] == PipelineResult.UNRELATED_CONTENT.value


@pytest.mark.integration
class TestPipelineErrorHandling:
    """Tests for error handling in the pipeline."""

    @pytest.mark.asyncio
    async def test_extraction_failure(self, test_db):
        """Test handling of content extraction failure."""
        with patch.object(IncidentService, "_get_orchestrator") as mock_get_orch:
            mock_orchestrator = MagicMock()
            mock_orchestrator.run_full_analysis_from_url = AsyncMock(
                return_value=PipelineOutput(
                    status=PipelineResult.FAILED_EXTRACTION,
                    error_message="Could not fetch URL",
                )
            )
            mock_get_orch.return_value = mock_orchestrator

            result = await IncidentService.create_report_from_url(
                "https://invalid-url.example.com/404"
            )

        assert result.status == PipelineResult.FAILED_EXTRACTION
        assert result.source is None

    @pytest.mark.asyncio
    async def test_analysis_failure_raises_http_exception(self, test_db):
        """Test that analysis failure with incidents raises HTTP exception."""
        from fastapi import HTTPException

        # Create a source and incident - HTTPException only raised when
        # there are incidents/overviews but status indicates failure
        source = create_test_source(
            text="Test article for analysis failure scenario testing here.",
            url="https://example.com/fail",
        )
        incident = create_test_incident()

        output = PipelineOutput(
            source=source,
            status=PipelineResult.FAILED_FORMATTING,  # A failure status
            incidents=[incident],  # Has incidents, so HTTPException will be raised
            error_message="Formatting failed after analysis",
        )

        with pytest.raises(HTTPException) as exc_info:
            await IncidentService._create_report(output)

        assert exc_info.value.status_code == 422
        assert "FAILED_FORMATTING" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_analysis_failure_without_incidents_returns_output(self, test_db):
        """Test that analysis failure without incidents returns output (no exception)."""
        source = create_test_source(
            text="Test article for analysis failure without incidents.",
            url="https://example.com/fail-no-incidents",
        )

        output = PipelineOutput(
            source=source,
            status=PipelineResult.FAILED_ANALYSIS,
            incidents=[],
            error_message="LLM returned invalid response",
        )

        # Should return output, not raise exception
        result = await IncidentService._create_report(output)

        assert result.status == PipelineResult.FAILED_ANALYSIS
        assert result.error_message == "LLM returned invalid response"
