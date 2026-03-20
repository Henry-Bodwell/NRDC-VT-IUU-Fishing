"""
Unit tests for service layer (IncidentService, SourceService, OverviewService).

These tests mock external dependencies (DSPy, database operations) to test
service logic in isolation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.service.incident_service import IncidentService
from app.service.source_service import SourceService
from app.service.overview_service import OverviewService
from app.models.sources import Source
from app.models.incidents import IndustryOverview
from app.dspy_files.news_analysis import PipelineOutput, PipelineResult


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
    async def test_create_report_from_url_success(self):
        """Test successful report creation from URL."""
        url = "https://example.com/test-article"

        with patch.object(
            IncidentService, "_get_orchestrator"
        ) as mock_get_orch, patch.object(
            IncidentService, "_create_report"
        ) as mock_create:
            mock_orchestrator = AsyncMock()
            mock_get_orch.return_value = mock_orchestrator

            mock_source = MagicMock(spec=Source)
            mock_source.url = url
            mock_source.article_text = "Test article"
            mock_source.article_hash = None

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

            result = await IncidentService.create_report_from_url(url)

            mock_get_orch.assert_called_once()
            mock_orchestrator.run_full_analysis_from_url.assert_called_once_with(
                url=url
            )
            mock_create.assert_called_once_with(mock_output)
            assert result == mock_output

    @pytest.mark.asyncio
    async def test_create_report_from_text(self):
        """Test report creation from text input."""
        text = "Test article text about illegal fishing operations."
        title = "Test Title"
        author = "Test Author"

        with patch.object(
            IncidentService, "_get_orchestrator"
        ) as mock_get_orch, patch.object(
            IncidentService, "_create_report"
        ) as mock_create:
            mock_orchestrator = AsyncMock()
            mock_get_orch.return_value = mock_orchestrator

            mock_source = MagicMock(spec=Source)
            mock_source.article_text = text
            mock_source.article_hash = None

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

            result = await IncidentService.create_report_from_text(
                text=text, title=title, author=author
            )

            mock_orchestrator.run_full_analysis_from_text.assert_called_once()
            call_kwargs = mock_orchestrator.run_full_analysis_from_text.call_args.kwargs
            assert call_kwargs["text"] == text
            assert call_kwargs["title"] == title
            assert call_kwargs["author"] == author
            assert result == mock_output


@pytest.mark.unit
class TestSourceService:
    """Tests for SourceService."""

    @pytest.mark.asyncio
    async def test_update_source(self):
        """Test updating a source."""
        source_id = "507f1f77bcf86cd799439011"
        update_data = {"status": "modified", "verified": True}

        mock_source = MagicMock(spec=Source)
        mock_source.id = source_id
        mock_source.status = "modified"
        mock_source.verified = True

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
    async def test_delete_source(self):
        """Test deleting a source."""
        source_id = "507f1f77bcf86cd799439011"

        with patch("app.service.service.Service.delete") as mock_delete:
            mock_delete.return_value = True

            result = await SourceService.delete_source(source_id)

            mock_delete.assert_called_once_with(
                model_cls=Source,
                model_id=source_id,
                model_name="source",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_update_source_not_found(self):
        """Test updating a non-existent source raises HTTPException."""
        from fastapi import HTTPException

        source_id = "507f1f77bcf86cd799439011"
        update_data = {"status": "modified"}

        with patch("app.service.service.Service.update_model") as mock_update:
            mock_update.side_effect = HTTPException(
                status_code=404,
                detail="source with ID 507f1f77bcf86cd799439011 not found",
            )

            with pytest.raises(HTTPException) as exc_info:
                await SourceService.update_source(source_id, update_data)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_source_not_found(self):
        """Test deleting a non-existent source raises HTTPException."""
        from fastapi import HTTPException

        source_id = "507f1f77bcf86cd799439011"

        with patch("app.service.service.Service.delete") as mock_delete:
            mock_delete.side_effect = HTTPException(
                status_code=404,
                detail="source with ID 507f1f77bcf86cd799439011 not found",
            )

            with pytest.raises(HTTPException) as exc_info:
                await SourceService.delete_source(source_id)

            assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestOverviewService:
    """Tests for OverviewService."""

    @pytest.mark.asyncio
    async def test_update_overview(self):
        """Test updating an industry overview."""
        overview_id = "507f1f77bcf86cd799439011"
        update_data = {"status": "modified", "verified": True}

        mock_overview = MagicMock(spec=IndustryOverview)
        mock_overview.id = overview_id
        mock_overview.status = "modified"
        mock_overview.verified = True

        with patch("app.service.service.Service.update_model") as mock_update:
            mock_update.return_value = mock_overview

            result = await OverviewService.update_overview(overview_id, update_data)

            mock_update.assert_called_once_with(
                model_cls=IndustryOverview,
                model_id=overview_id,
                update_data=update_data,
                model_name="industry_overviews",
            )
            assert result == mock_overview

    @pytest.mark.asyncio
    async def test_delete_overview(self):
        """Test deleting an industry overview."""
        overview_id = "507f1f77bcf86cd799439011"

        with patch("app.service.service.Service.delete") as mock_delete:
            mock_delete.return_value = True

            result = await OverviewService.delete_overview(overview_id)

            mock_delete.assert_called_once_with(
                model_cls=IndustryOverview,
                model_id=overview_id,
                model_name="industry_overviews",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_update_overview_not_found(self):
        """Test updating a non-existent overview raises HTTPException."""
        from fastapi import HTTPException

        overview_id = "507f1f77bcf86cd799439011"
        update_data = {"status": "modified"}

        with patch("app.service.service.Service.update_model") as mock_update:
            mock_update.side_effect = HTTPException(
                status_code=404,
                detail="industry_overviews with ID 507f1f77bcf86cd799439011 not found",
            )

            with pytest.raises(HTTPException) as exc_info:
                await OverviewService.update_overview(overview_id, update_data)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_overview_not_found(self):
        """Test deleting a non-existent overview raises HTTPException."""
        from fastapi import HTTPException

        overview_id = "507f1f77bcf86cd799439011"

        with patch("app.service.service.Service.delete") as mock_delete:
            mock_delete.side_effect = HTTPException(
                status_code=404,
                detail="industry_overviews with ID 507f1f77bcf86cd799439011 not found",
            )

            with pytest.raises(HTTPException) as exc_info:
                await OverviewService.delete_overview(overview_id)

            assert exc_info.value.status_code == 404
