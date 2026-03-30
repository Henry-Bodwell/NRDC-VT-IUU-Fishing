"""
Unit tests for source reclassification via update_source.

When article_scope is changed through update_source, the system should:
1. Run re-analysis with the new scope FIRST (no DB mutations yet)
2. Only on success: clean up old linked documents
   - If this source is the only source on a document -> delete it
   - If the document has other sources -> just unlink this source
3. Save new results and update the source

If re-analysis fails, nothing is changed (transaction safety).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from app.service.source_service import SourceService
from app.models.sources import Source, ArticleScopeClassification
from app.models.incidents import IncidentReport, IndustryOverview
from app.dspy_files.news_analysis import PipelineOutput, PipelineResult


def _make_source_mock(source_id, scope_type, incidents=None, overview=None):
    """Helper to build a mock Source with common defaults."""
    mock = MagicMock(spec=Source)
    mock.id = ObjectId(source_id)
    mock.article_scope = ArticleScopeClassification(
        articleType=scope_type, confidence=0.9
    )
    mock.article_text = "Test article"
    mock.article_hash = "fakehash123"
    mock.incidents = incidents or []
    mock.overview = overview
    mock.save = AsyncMock()
    return mock


def _make_incident_link(incident_id):
    """Helper to build a mock Link to an IncidentReport."""
    link = MagicMock()
    link.ref = MagicMock()
    link.ref.id = ObjectId(incident_id)
    return link


def _make_overview_link(overview_id):
    """Helper to build a mock Link to an IndustryOverview."""
    link = MagicMock()
    link.ref = MagicMock()
    link.ref.id = ObjectId(overview_id)
    return link


def _source_get_returning(source_mock, refreshed_mock=None):
    """Build an async side_effect for Source.get that returns source_mock
    on first call and refreshed_mock on second call (the re-fetch)."""
    if refreshed_mock is None:
        refreshed_mock = source_mock
    calls = iter([source_mock, refreshed_mock])

    async def _get(*args, **kwargs):
        return next(calls, refreshed_mock)

    return _get


@pytest.mark.unit
class TestReclassifyViaUpdate:
    """Tests for reclassification triggered through SourceService.update_source."""

    @pytest.mark.asyncio
    async def test_update_without_scope_delegates_to_base(self):
        """Updating fields without article_scope uses normal update path."""
        source_id = str(ObjectId())
        update_data = {"article_title": "New Title"}

        mock_source = MagicMock(spec=Source)

        with patch("app.service.service.Service.update_model") as mock_update:
            mock_update.return_value = mock_source

            result = await SourceService.update_source(source_id, update_data)

            mock_update.assert_called_once_with(
                model_cls=Source,
                model_id=source_id,
                update_data=update_data,
                model_name="source",
            )
            assert result == mock_source

    @pytest.mark.asyncio
    async def test_same_scope_delegates_to_base(self):
        """Updating article_scope to same value uses normal update path."""
        source_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Single Incident",
                "confidence": 0.95,
            }
        }

        mock_source = _make_source_mock(source_id, "Single Incident")

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                return_value=mock_source,
            ),
            patch("app.service.service.Service.update_model") as mock_update,
        ):
            mock_update.return_value = mock_source
            await SourceService.update_source(source_id, update_data)

            mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_scope_change_runs_analysis_before_cleanup(self):
        """Analysis runs BEFORE deleting old docs (transaction safety)."""
        source_id = str(ObjectId())
        incident_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Industry Overview",
                "confidence": 1.0,
            }
        }

        mock_source = _make_source_mock(
            source_id,
            "Single Incident",
            incidents=[_make_incident_link(incident_id)],
        )

        mock_incident = MagicMock(spec=IncidentReport)
        mock_incident.id = ObjectId(incident_id)
        mock_incident.sources = [MagicMock()]  # sole source
        mock_incident.delete = AsyncMock()

        mock_pipeline_output = PipelineOutput(
            source=mock_source,
            status=PipelineResult.SUCCESS,
            industry_overview=MagicMock(spec=IndustryOverview),
        )

        call_order = []

        async def track_analyze(*args, **kwargs):
            call_order.append("analyze")
            return mock_pipeline_output

        async def track_delete(*args, **kwargs):
            call_order.append("delete_incident")

        mock_incident.delete = AsyncMock(side_effect=track_delete)

        refreshed_source = MagicMock(spec=Source)
        refreshed_source.id = ObjectId(source_id)

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                side_effect=_source_get_returning(mock_source, refreshed_source),
            ),
            patch.object(
                IncidentReport,
                "get",
                new_callable=AsyncMock,
                return_value=mock_incident,
            ),
            patch(
                "app.service.source_service.IncidentService.analyze_existing_source",
                new_callable=AsyncMock,
                side_effect=track_analyze,
            ),
            patch(
                "app.service.source_service.IncidentService.save_pipeline_output",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
        ):
            await SourceService.update_source(source_id, update_data)

            # Analysis must happen BEFORE deletion
            assert call_order == ["analyze", "delete_incident"]

    @pytest.mark.asyncio
    async def test_analysis_failure_leaves_old_docs_intact(self):
        """If analysis fails, old incidents are NOT deleted."""
        source_id = str(ObjectId())
        incident_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Industry Overview",
                "confidence": 1.0,
            }
        }

        mock_source = _make_source_mock(
            source_id,
            "Single Incident",
            incidents=[_make_incident_link(incident_id)],
        )

        mock_incident = MagicMock(spec=IncidentReport)
        mock_incident.id = ObjectId(incident_id)
        mock_incident.sources = [MagicMock()]
        mock_incident.delete = AsyncMock()

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                return_value=mock_source,
            ),
            patch.object(
                IncidentReport,
                "get",
                new_callable=AsyncMock,
                return_value=mock_incident,
            ),
            patch(
                "app.service.source_service.IncidentService.analyze_existing_source",
                new_callable=AsyncMock,
                side_effect=Exception("LLM call failed"),
            ),
        ):
            with pytest.raises(Exception, match="LLM call failed"):
                await SourceService.update_source(source_id, update_data)

            # Old incident must NOT have been deleted
            mock_incident.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_sole_source_incident_deleted(self):
        """Incident with only this source gets deleted on reclassify."""
        source_id = str(ObjectId())
        incident_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Industry Overview",
                "confidence": 1.0,
            }
        }

        mock_source = _make_source_mock(
            source_id,
            "Single Incident",
            incidents=[_make_incident_link(incident_id)],
        )

        mock_incident = MagicMock(spec=IncidentReport)
        mock_incident.id = ObjectId(incident_id)
        mock_incident.sources = [MagicMock()]  # sole source
        mock_incident.delete = AsyncMock()
        mock_incident.remove_source = AsyncMock()

        mock_pipeline_output = PipelineOutput(
            source=mock_source,
            status=PipelineResult.SUCCESS,
            industry_overview=MagicMock(spec=IndustryOverview),
        )

        refreshed_source = MagicMock(spec=Source)

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                side_effect=_source_get_returning(mock_source, refreshed_source),
            ),
            patch.object(
                IncidentReport,
                "get",
                new_callable=AsyncMock,
                return_value=mock_incident,
            ),
            patch(
                "app.service.source_service.IncidentService.analyze_existing_source",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
            patch(
                "app.service.source_service.IncidentService.save_pipeline_output",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
        ):
            await SourceService.update_source(source_id, update_data)

            mock_incident.delete.assert_called_once()
            mock_incident.remove_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_source_incident_unlinked_not_deleted(self):
        """Incident with multiple sources only gets unlinked."""
        source_id = str(ObjectId())
        incident_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Industry Overview",
                "confidence": 1.0,
            }
        }

        mock_source = _make_source_mock(
            source_id,
            "Single Incident",
            incidents=[_make_incident_link(incident_id)],
        )

        mock_incident = MagicMock(spec=IncidentReport)
        mock_incident.id = ObjectId(incident_id)
        mock_incident.sources = [MagicMock(), MagicMock()]  # 2 sources
        mock_incident.delete = AsyncMock()
        mock_incident.remove_source = AsyncMock()

        mock_pipeline_output = PipelineOutput(
            source=mock_source,
            status=PipelineResult.SUCCESS,
            industry_overview=MagicMock(spec=IndustryOverview),
        )

        refreshed_source = MagicMock(spec=Source)

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                side_effect=_source_get_returning(mock_source, refreshed_source),
            ),
            patch.object(
                IncidentReport,
                "get",
                new_callable=AsyncMock,
                return_value=mock_incident,
            ),
            patch(
                "app.service.source_service.IncidentService.analyze_existing_source",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
            patch(
                "app.service.source_service.IncidentService.save_pipeline_output",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
        ):
            await SourceService.update_source(source_id, update_data)

            mock_incident.remove_source.assert_called_once_with(mock_source)
            mock_incident.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_overview_deleted_on_reclassify(self):
        """Linked overview gets deleted when scope changes."""
        source_id = str(ObjectId())
        overview_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Single Incident",
                "confidence": 1.0,
            }
        }

        mock_overview = MagicMock(spec=IndustryOverview)
        mock_overview.id = ObjectId(overview_id)
        mock_overview.delete = AsyncMock()

        mock_source = _make_source_mock(
            source_id,
            "Industry Overview",
            overview=_make_overview_link(overview_id),
        )

        mock_pipeline_output = PipelineOutput(
            source=mock_source,
            status=PipelineResult.SUCCESS,
            incidents=[MagicMock(spec=IncidentReport)],
        )

        refreshed_source = MagicMock(spec=Source)

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                side_effect=_source_get_returning(mock_source, refreshed_source),
            ),
            patch.object(
                IndustryOverview,
                "get",
                new_callable=AsyncMock,
                return_value=mock_overview,
            ),
            patch(
                "app.service.source_service.IncidentService.analyze_existing_source",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
            patch(
                "app.service.source_service.IncidentService.save_pipeline_output",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
        ):
            await SourceService.update_source(source_id, update_data)

            mock_overview.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_reclassify_to_unrelated_skips_analysis(self):
        """Reclassifying to Unrelated cleans up docs without re-analysis."""
        source_id = str(ObjectId())
        incident_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Unrelated to IUU Fishing",
                "confidence": 1.0,
            }
        }

        mock_source = _make_source_mock(
            source_id,
            "Single Incident",
            incidents=[_make_incident_link(incident_id)],
        )

        mock_incident = MagicMock(spec=IncidentReport)
        mock_incident.id = ObjectId(incident_id)
        mock_incident.sources = [MagicMock()]  # sole source
        mock_incident.delete = AsyncMock()

        refreshed_source = MagicMock(spec=Source)

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                side_effect=_source_get_returning(mock_source, refreshed_source),
            ),
            patch.object(
                IncidentReport,
                "get",
                new_callable=AsyncMock,
                return_value=mock_incident,
            ),
            patch(
                "app.service.source_service.IncidentService.analyze_existing_source",
                new_callable=AsyncMock,
            ) as mock_analyze,
        ):
            await SourceService.update_source(source_id, update_data)

            mock_incident.delete.assert_called_once()
            mock_analyze.assert_not_called()
            mock_source.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixed_sole_and_shared_incidents(self):
        """Sole-source incidents deleted, shared incidents only unlinked."""
        source_id = str(ObjectId())
        sole_id = str(ObjectId())
        shared_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Single Incident",
                "confidence": 1.0,
            }
        }

        mock_source = _make_source_mock(
            source_id,
            "Multiple Incidents",
            incidents=[
                _make_incident_link(sole_id),
                _make_incident_link(shared_id),
            ],
        )

        sole_incident = MagicMock(spec=IncidentReport)
        sole_incident.id = ObjectId(sole_id)
        sole_incident.sources = [MagicMock()]  # length 1
        sole_incident.delete = AsyncMock()
        sole_incident.remove_source = AsyncMock()

        shared_incident = MagicMock(spec=IncidentReport)
        shared_incident.id = ObjectId(shared_id)
        shared_incident.sources = [MagicMock(), MagicMock()]  # length 2
        shared_incident.delete = AsyncMock()
        shared_incident.remove_source = AsyncMock()

        async def get_incident(iid, **kwargs):
            iid_str = str(iid)
            if iid_str == sole_id:
                return sole_incident
            if iid_str == shared_id:
                return shared_incident
            return None

        mock_pipeline_output = PipelineOutput(
            source=mock_source,
            status=PipelineResult.SUCCESS,
            incidents=[MagicMock(spec=IncidentReport)],
        )

        refreshed_source = MagicMock(spec=Source)

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                side_effect=_source_get_returning(mock_source, refreshed_source),
            ),
            patch.object(
                IncidentReport,
                "get",
                new_callable=AsyncMock,
                side_effect=get_incident,
            ),
            patch(
                "app.service.source_service.IncidentService.analyze_existing_source",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
            patch(
                "app.service.source_service.IncidentService.save_pipeline_output",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
        ):
            await SourceService.update_source(source_id, update_data)

            sole_incident.delete.assert_called_once()
            sole_incident.remove_source.assert_not_called()
            shared_incident.remove_source.assert_called_once_with(mock_source)
            shared_incident.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_scope_change_passes_correct_scope_to_analyzer(self):
        """The new scope value is forwarded to analyze_existing_source."""
        source_id = str(ObjectId())
        update_data = {
            "article_scope": {
                "articleType": "Multiple Incidents",
                "confidence": 1.0,
            }
        }

        mock_source = _make_source_mock(source_id, "Single Incident")

        mock_pipeline_output = PipelineOutput(
            source=mock_source,
            status=PipelineResult.SUCCESS,
            incidents=[MagicMock(spec=IncidentReport)],
        )

        refreshed_source = MagicMock(spec=Source)

        with (
            patch.object(
                Source,
                "get",
                new_callable=AsyncMock,
                side_effect=_source_get_returning(mock_source, refreshed_source),
            ),
            patch(
                "app.service.source_service.IncidentService.analyze_existing_source",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ) as mock_analyze,
            patch(
                "app.service.source_service.IncidentService.save_pipeline_output",
                new_callable=AsyncMock,
                return_value=mock_pipeline_output,
            ),
        ):
            await SourceService.update_source(source_id, update_data)

            mock_analyze.assert_called_once_with(
                source=mock_source,
                assumed_scope="Multiple Incidents",
            )
