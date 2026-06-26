"""
End-to-end skeleton for the RAG-backed multi-incident analysis pipeline.

This documents intent for the upcoming chunking/RAG rework: a long,
multi-incident article should be chunked, indexed into Qdrant, segmented into
multiple incidents, and the incidents extracted via category-scoped retrieval.

This is a SKELETON. Wiring a real orchestrator with a live LLM + Qdrant is
expensive and not yet implemented, so the test currently skips with a clear
reason. A human should fill in the assertions once the RAG pipeline is wired.

NOTE: app.rag.* and the RAG-aware orchestrator path do not exist yet -- this
is the intended red state for the rework.
"""

import os

import pytest

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

LONG_MULTI_INCIDENT_TEXT = (
    "In January, the trawler Ocean Raider was seized off the coast for "
    "fishing without a valid license; the crew were detained and the catch "
    "of bluefin tuna confiscated. "
    "Separately, in March, the longliner Sea Wanderer was boarded after "
    "inspectors found undeclared swordfish mislabeled for export, and several "
    "crew members reported forced-labor conditions aboard. "
    "Later that year, the reefer vessel Cold Current was implicated in an "
    "illegal transshipment in a regional fishery management area, transferring "
    "catch from unregistered vessels on the high seas. "
) * 40


def _qdrant_reachable(url: str) -> bool:
    """Best-effort reachability probe for a Qdrant HTTP endpoint."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url, timeout=2.0)
        client.get_collections()
        client.close()
        return True
    except Exception:
        return False


def _openai_key_available() -> bool:
    """True only when a real (non-dummy) OpenAI key is configured."""
    key = os.getenv("OPENAI_API_KEY")
    return bool(key) and key != "test-key"


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_rag_pipeline_end_to_end(test_db):
    """
    Ingest a long multi-incident text and assert RAG behavior end-to-end.

    Intended final assertions (fill in once the pipeline is wired):
      1. output.status == PipelineResult.SUCCESS
      2. len(output.incidents) > 1  (multiple incidents discovered)
      3. The source's chunks are present in Qdrant (retrieve returns chunks
         filtered by the source's id / article_hash).

    Until the RAG orchestrator path is wired, this skips with a clear reason
    so a human knows exactly what remains.
    """
    if not _qdrant_reachable(QDRANT_URL):
        pytest.skip(f"Qdrant not reachable at {QDRANT_URL}")
    if not _openai_key_available():
        pytest.skip("OPENAI_API_KEY missing or dummy 'test-key'")

    pytest.skip("pending RAG pipeline wiring")

    # --- Scaffold for the human to complete -----------------------------
    # from app.dspy_files.news_analysis import AnalysisOrchestrator, PipelineResult
    #
    # orchestrator = AnalysisOrchestrator(api_key=os.environ["OPENAI_API_KEY"])
    # output = await orchestrator.run_full_analysis_from_text(
    #     text=LONG_MULTI_INCIDENT_TEXT,
    #     title="Multi-incident IUU roundup",
    #     status="user_input",
    # )
    #
    # assert output.status == PipelineResult.SUCCESS
    # assert len(output.incidents) > 1
    #
    # # Verify chunks landed in Qdrant for this source.
    # from qdrant_client import AsyncQdrantClient
    # from app.dspy_files.config import make_embedder
    # from app.rag.vector_store import VectorStore
    #
    # client = AsyncQdrantClient(url=QDRANT_URL)
    # store = VectorStore(client, make_embedder())
    # chunks = await store.retrieve(
    #     "illegal fishing vessel seizure",
    #     k=5,
    #     source_id=str(output.source.id),
    # )
    # assert len(chunks) > 0
    # await client.close()
