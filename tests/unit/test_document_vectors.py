"""Unit tests for document-level vectors (VectorStore methods + index helpers).

The Qdrant client and embedder are mocked; behaviour against a live Qdrant is
covered by running scripts/backfill_document_vectors.py.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beanie import PydanticObjectId

from app.models.duplicates import ordered_pair
from app.rag import document_index
from app.rag.document_text import incident_embedding_text
from app.rag.vector_store import (
    DOC_TYPE_INCIDENT,
    DOC_TYPE_OVERVIEW,
    DOCUMENT_COLLECTION,
    VectorStore,
    document_point_id,
    point_id,
)
from tests.conftest import make_classification, make_extracted_data


def fake_incident(id=None, **data_overrides):
    """Duck-typed incident: the code under test only reads attributes, and a
    real IncidentReport requires an initialised Beanie collection."""
    return SimpleNamespace(
        id=id,
        embedding_text_hash=None,
        sources=[],
        extracted_information=make_extracted_data(**data_overrides),
        incident_classification=make_classification(),
    )


def _store():
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=True)
    client.create_payload_index = AsyncMock()
    client.upsert = AsyncMock()
    client.retrieve = AsyncMock()
    client.query_points = AsyncMock()
    client.scroll = AsyncMock()
    client.delete = AsyncMock()
    embedder = MagicMock(side_effect=lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    return VectorStore(
        client,
        embedder,
        collection=DOCUMENT_COLLECTION,
        index_fields=("doc_type", "doc_id"),
    )


@pytest.mark.unit
class TestDocumentPointId:
    def test_deterministic_and_type_scoped(self):
        assert document_point_id("incident", "abc") == document_point_id(
            "incident", "abc"
        )
        assert document_point_id("incident", "abc") != document_point_id(
            "overview", "abc"
        )

    def test_does_not_collide_with_chunk_ids(self):
        assert document_point_id("incident", "0") != point_id("incident", 0)


@pytest.mark.unit
class TestVectorStoreDocuments:
    async def test_ensure_collection_indexes_configured_fields(self):
        store = _store()
        await store.ensure_collection()
        fields = [
            c.kwargs["field_name"]
            for c in store.client.create_payload_index.call_args_list
        ]
        assert fields == ["doc_type", "doc_id"]

    async def test_upsert_documents_payload_and_ids(self):
        store = _store()
        n = await store.upsert_documents(
            [(DOC_TYPE_INCIDENT, "id1", "text one", {"event_date": "2024"})]
        )
        assert n == 1
        point = store.client.upsert.call_args.kwargs["points"][0]
        assert point.id == document_point_id(DOC_TYPE_INCIDENT, "id1")
        assert point.payload == {
            "event_date": "2024",
            "doc_type": DOC_TYPE_INCIDENT,
            "doc_id": "id1",
        }

    async def test_upsert_documents_empty_is_noop(self):
        store = _store()
        assert await store.upsert_documents([]) == 0
        store.client.upsert.assert_not_called()

    async def test_similar_to_document_excludes_self_and_filters_type(self):
        store = _store()
        store.client.retrieve.return_value = [SimpleNamespace(vector=[1.0, 0.0])]
        store.client.query_points.return_value = SimpleNamespace(
            points=[
                SimpleNamespace(
                    payload={"doc_type": DOC_TYPE_INCIDENT, "doc_id": "id2"},
                    score=0.93,
                )
            ]
        )

        hits = await store.similar_to_document(
            DOC_TYPE_INCIDENT,
            "id1",
            k=5,
            doc_types=[DOC_TYPE_INCIDENT],
            score_threshold=0.8,
        )

        assert [(h.doc_id, h.score) for h in hits] == [("id2", 0.93)]
        kwargs = store.client.query_points.call_args.kwargs
        assert kwargs["limit"] == 5
        assert kwargs["score_threshold"] == 0.8
        query_filter = kwargs["query_filter"]
        assert query_filter.must[0].key == "doc_type"
        assert query_filter.must_not[0].has_id == [
            document_point_id(DOC_TYPE_INCIDENT, "id1")
        ]

    async def test_similar_to_unindexed_document_returns_empty(self):
        store = _store()
        store.client.retrieve.return_value = []
        assert await store.similar_to_document(DOC_TYPE_INCIDENT, "missing") == []
        store.client.query_points.assert_not_called()

    async def test_scroll_vectors_pages_until_exhausted(self):
        store = _store()
        page1 = [
            SimpleNamespace(
                payload={"doc_type": DOC_TYPE_INCIDENT, "doc_id": "a"}, vector=[1, 0]
            )
        ]
        page2 = [
            SimpleNamespace(
                payload={"doc_type": DOC_TYPE_OVERVIEW, "doc_id": "b"}, vector=[0, 1]
            )
        ]
        store.client.scroll.side_effect = [(page1, "next"), (page2, None)]

        vectors = await store.scroll_vectors()
        assert [(v.doc_type, v.doc_id, v.vector) for v in vectors] == [
            (DOC_TYPE_INCIDENT, "a", [1.0, 0.0]),
            (DOC_TYPE_OVERVIEW, "b", [0.0, 1.0]),
        ]
        assert store.client.scroll.call_args_list[1].kwargs["offset"] == "next"

    async def test_delete_document_by_point_id(self):
        store = _store()
        await store.delete_document(DOC_TYPE_INCIDENT, "id1")
        selector = store.client.delete.call_args.kwargs["points_selector"]
        assert selector.points == [document_point_id(DOC_TYPE_INCIDENT, "id1")]


@pytest.mark.unit
class TestIndexIncidents:
    async def test_skips_unchanged_and_indexes_changed(self):
        unchanged = fake_incident(id=PydanticObjectId())
        unchanged.embedding_text_hash = incident_embedding_text(unchanged)[1]
        changed = fake_incident(id=PydanticObjectId())

        store = MagicMock()
        store.upsert_documents = AsyncMock(return_value=1)
        with (
            patch.object(document_index, "get_document_store", return_value=store),
            patch.object(document_index, "_store_hash", AsyncMock()) as store_hash,
        ):
            n = await document_index.index_incidents([unchanged, changed])

        assert n == 1
        items = store.upsert_documents.call_args.args[0]
        assert [i[1] for i in items] == [str(changed.id)]
        store_hash.assert_awaited_once()

    async def test_unsaved_incidents_are_skipped(self):
        store = MagicMock()
        store.upsert_documents = AsyncMock()
        with patch.object(document_index, "get_document_store", return_value=store):
            assert await document_index.index_incidents([fake_incident()]) == 0
        store.upsert_documents.assert_not_called()

    async def test_store_failure_is_swallowed(self):
        store = MagicMock()
        store.upsert_documents = AsyncMock(side_effect=RuntimeError("qdrant down"))
        with patch.object(document_index, "get_document_store", return_value=store):
            ok = await document_index.index_incident(
                fake_incident(id=PydanticObjectId())
            )
        assert ok is False


@pytest.mark.unit
class TestOrderedPair:
    def test_canonical_order(self):
        a, b = PydanticObjectId(), PydanticObjectId()
        assert ordered_pair(a, b) == ordered_pair(b, a)
        low, high = ordered_pair(a, b)
        assert str(low) < str(high)
