"""
Unit tests for AnalysisOrchestrator's RAG indexing decisions.

Covers analysis_from_source():
- Only incident scopes are indexed; overviews and unrelated sources never are
- Chunks from indexing are passed through to analysis
- Chunks indexed for a never-saved source are discarded when analysis fails
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import app.models  # noqa: F401  # resolve the models <-> pipeline import cycle first
from app.dspy_files.news_analysis import AnalysisOrchestrator, PipelineResult


def make_source(article_type: str, source_id=None) -> MagicMock:
    source = MagicMock()
    source.id = source_id
    source.article_hash = "hash-1"
    source.article_scope = MagicMock(articleType=article_type)
    return source


def make_orchestrator() -> AnalysisOrchestrator:
    with patch("app.dspy_files.news_analysis.ContentExtractor"), patch(
        "app.dspy_files.news_analysis.AnalysisPipeline"
    ):
        orchestrator = AnalysisOrchestrator(api_key="test-key")
    orchestrator.classify_source = AsyncMock(side_effect=lambda s, cb=None: s)
    orchestrator.format_output = AsyncMock(return_value=MagicMock())
    return orchestrator


class TestRagIndexingScope:
    @pytest.mark.asyncio
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "article_type", ["Industry Overview", "Unrelated to IUU Fishing"]
    )
    async def test_non_incident_scopes_are_not_indexed(self, article_type):
        orchestrator = make_orchestrator()
        orchestrator.index_source_for_rag = AsyncMock()
        orchestrator.analyze_source = AsyncMock(return_value=MagicMock())

        await orchestrator.analysis_from_source(make_source(article_type))

        orchestrator.index_source_for_rag.assert_not_awaited()
        assert orchestrator.analyze_source.await_args.kwargs["use_rag"] is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_incident_scope_passes_indexed_chunks_to_analysis(self):
        orchestrator = make_orchestrator()
        store, chunks = MagicMock(), [MagicMock()]
        orchestrator.index_source_for_rag = AsyncMock(
            return_value=(store, True, chunks)
        )
        orchestrator.analyze_source = AsyncMock(return_value=MagicMock())

        await orchestrator.analysis_from_source(make_source("Single Incident"))

        kwargs = orchestrator.analyze_source.await_args.kwargs
        assert kwargs["store"] is store
        assert kwargs["use_rag"] is True
        assert kwargs["chunks"] is chunks


class TestDiscardUnsavedChunks:
    @pytest.fixture(autouse=True)
    def loose_pipeline_output(self):
        """PipelineOutput validates ``source`` as a real Source; mocks suffice here."""
        with patch(
            "app.dspy_files.news_analysis.PipelineOutput",
            side_effect=lambda **kwargs: MagicMock(**kwargs),
        ):
            yield

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_failed_analysis_of_unsaved_source_discards_chunks(self):
        orchestrator = make_orchestrator()
        store = MagicMock(delete_source=AsyncMock())
        orchestrator.index_source_for_rag = AsyncMock(return_value=(store, True, []))
        orchestrator.analyze_source = AsyncMock(side_effect=RuntimeError("boom"))

        output = await orchestrator.analysis_from_source(
            make_source("Multiple Incidents")
        )

        assert output.status == PipelineResult.FAILED_ANALYSIS
        store.delete_source.assert_awaited_once_with("hash-1")

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_failed_reanalysis_of_saved_source_keeps_chunks(self):
        orchestrator = make_orchestrator()
        store = MagicMock(delete_source=AsyncMock())
        orchestrator.index_source_for_rag = AsyncMock(return_value=(store, True, []))
        orchestrator.analyze_source = AsyncMock(side_effect=RuntimeError("boom"))

        await orchestrator.analysis_from_source(
            make_source("Single Incident", source_id="65f0c0ffee")
        )

        store.delete_source.assert_not_awaited()
