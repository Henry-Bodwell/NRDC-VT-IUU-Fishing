"""Unit tests for ClusterService: rebuilds, curation, assignment and summaries.

Qdrant is replaced by an in-memory FakeDocumentStore and the LLM by a stub
summarizer; MongoDB is real (the ``test_db`` fixture), like other unit tests
that touch Beanie documents.
"""

from unittest.mock import patch

import numpy as np
import pytest
from beanie import PydanticObjectId

from app.auth import get_current_user
from app.main import app
from app.models.clusters import Cluster, member_key
from app.rag.vector_store import (
    DOC_TYPE_CLUSTER,
    DOC_TYPE_INCIDENT,
    DocumentHit,
    DocumentVector,
)
from app.service.cluster_service import ClusterService
from tests.conftest import make_extracted_data, make_incident

DIM = 16


class FakeDocumentStore:
    """The subset of VectorStore that ClusterService uses, over a dict."""

    def __init__(self):
        self.vectors: dict[tuple[str, str], list[float]] = {}

    def put(self, doc_type: str, doc_id: str, vector) -> None:
        self.vectors[(doc_type, doc_id)] = [float(x) for x in vector]

    async def scroll_vectors(self, doc_types=None, batch_size=256):
        return [
            DocumentVector(doc_type=t, doc_id=i, vector=v)
            for (t, i), v in self.vectors.items()
            if not doc_types or t in doc_types
        ]

    async def get_document_vector(self, doc_type, doc_id):
        return self.vectors.get((doc_type, doc_id))

    async def get_document_vectors(self, keys):
        return {k: self.vectors[k] for k in keys if k in self.vectors}

    async def similar_to_vector(
        self, vector, k=10, *, doc_types=None, score_threshold=None, exclude=None
    ):
        query = np.asarray(vector, dtype=float)
        query = query / np.linalg.norm(query)
        hits = []
        for (t, i), v in self.vectors.items():
            if doc_types and t not in doc_types:
                continue
            if exclude is not None and (t, i) == tuple(exclude):
                continue
            other = np.asarray(v, dtype=float)
            score = float(query @ (other / np.linalg.norm(other)))
            if score_threshold is not None and score < score_threshold:
                continue
            hits.append(DocumentHit(doc_type=t, doc_id=i, score=score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    async def upsert_vectors(self, items):
        for doc_type, doc_id, vector, _ in items:
            self.put(doc_type, doc_id, vector)
        return len(items)

    async def delete_document(self, doc_type, doc_id):
        self.vectors.pop((doc_type, doc_id), None)


def _unit(index: int) -> np.ndarray:
    v = np.zeros(DIM)
    v[index] = 1.0
    return v


def _blob(center: np.ndarray, n: int, rng, noise: float = 0.02) -> list[np.ndarray]:
    return [center + rng.normal(scale=noise, size=DIM) for _ in range(n)]


@pytest.fixture
def store():
    fake = FakeDocumentStore()
    with patch("app.service.cluster_service.get_document_store", return_value=fake):
        yield fake


@pytest.fixture
def two_themes(store):
    """Six incidents around axis 0 ("A") and six around axis 1 ("B")."""
    rng = np.random.default_rng(0)
    themes = {}
    for name, axis in (("A", 0), ("B", 1)):
        ids = []
        for vec in _blob(_unit(axis), 6, rng):
            doc_id = str(PydanticObjectId())
            store.put(DOC_TYPE_INCIDENT, doc_id, vec)
            ids.append(doc_id)
        themes[name] = ids
    return themes


async def _auto_clusters(status: str = "active") -> list[Cluster]:
    return await Cluster.find(
        Cluster.origin == "auto", Cluster.status == status, fetch_links=False
    ).to_list()


async def _cluster_with(doc_id: str) -> Cluster:
    for cluster in await _auto_clusters():
        if member_key(DOC_TYPE_INCIDENT, doc_id) in cluster.member_keys():
            return cluster
    raise AssertionError(f"no active auto cluster contains {doc_id}")


async def _stub_summarizer(descriptions, aggregates):
    return {
        "title": "Generated title",
        "summary": f"Generated from {len(descriptions)} members.",
        "keywords": ["cod", " ", "trawling"],
    }


def _cos(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


# ── Rebuild ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRebuild:
    async def test_creates_one_cluster_per_theme(self, test_db, store, two_themes):
        stats = await ClusterService.rebuild(summarize=False)

        assert stats["created"] == 2
        clusters = await _auto_clusters()
        member_sets = sorted(
            sorted(k.split(":", 1)[1] for k in c.member_keys()) for c in clusters
        )
        assert member_sets == sorted(sorted(ids) for ids in two_themes.values())
        for cluster in clusters:
            assert (DOC_TYPE_CLUSTER, str(cluster.id)) in store.vectors

    async def test_second_rebuild_keeps_ids_and_skips_saves(
        self, test_db, store, two_themes
    ):
        await ClusterService.rebuild(summarize=False)
        before = {str(c.id): c.version for c in await _auto_clusters()}

        stats = await ClusterService.rebuild(summarize=False)

        assert stats["updated"] == 2 and stats["created"] == 0
        assert stats["saved"] == 0
        after = {str(c.id): c.version for c in await _auto_clusters()}
        assert after == before

    async def test_user_exclusion_survives_and_moves_centroid(
        self, test_db, store, two_themes
    ):
        # Pull one A member off-centre so excluding it visibly moves the centroid.
        removed = two_themes["A"][0]
        off = _unit(0) + 0.35 * _unit(7)
        store.put(DOC_TYPE_INCIDENT, removed, off)
        await ClusterService.rebuild(summarize=False, membership_threshold=0.99)
        cluster = await _cluster_with(removed)
        cluster_id = str(cluster.id)
        original = store.vectors[(DOC_TYPE_CLUSTER, cluster_id)]

        await ClusterService.remove_member(cluster, DOC_TYPE_INCIDENT, removed)
        await ClusterService.rebuild(summarize=False, membership_threshold=0.99)

        cluster = await Cluster.get(cluster_id, fetch_links=False)
        key = member_key(DOC_TYPE_INCIDENT, removed)
        assert cluster.status == "active"
        assert key not in cluster.member_keys()
        assert key in cluster.excluded_ids
        assert key not in cluster.member_scores
        rebuilt = store.vectors[(DOC_TYPE_CLUSTER, cluster_id)]
        assert _cos(rebuilt, off) < _cos(original, off)

    async def test_unmatched_auto_cluster_is_archived(self, test_db, store, two_themes):
        stale = Cluster(origin="auto")
        stale.set_members({member_key(DOC_TYPE_INCIDENT, str(PydanticObjectId())): 1})
        await stale.insert()
        store.put(DOC_TYPE_CLUSTER, str(stale.id), _unit(9))

        stats = await ClusterService.rebuild(summarize=False)

        assert stats["archived"] == 1
        stale = await Cluster.get(stale.id, fetch_links=False)
        assert stale.status == "archived"
        assert (DOC_TYPE_CLUSTER, str(stale.id)) not in store.vectors

    async def test_user_clusters_are_untouched(self, test_db, store, two_themes):
        user = await ClusterService.create(
            title="My cod cluster",
            members=[(DOC_TYPE_INCIDENT, i) for i in two_themes["A"][:2]],
        )
        version = user.version

        await ClusterService.rebuild(summarize=False)

        user = await Cluster.get(user.id, fetch_links=False)
        assert user.origin == "user"
        assert user.version == version
        assert len(user.member_keys()) == 2

    async def test_dry_run_writes_nothing(self, test_db, store, two_themes):
        stats = await ClusterService.rebuild(dry_run=True)

        assert len(stats["proposals"]) == 2
        assert await Cluster.find_all().count() == 0
        assert not [k for k in store.vectors if k[0] == DOC_TYPE_CLUSTER]


# ── Incremental assignment ─────────────────────────────────────────


@pytest.mark.unit
class TestAssignDocument:
    async def _new_doc_near(self, store, axis: int) -> str:
        doc_id = str(PydanticObjectId())
        store.put(DOC_TYPE_INCIDENT, doc_id, _unit(axis) + 0.01 * _unit(3))
        return doc_id

    async def test_joins_the_nearby_auto_cluster_only(self, test_db, store, two_themes):
        await ClusterService.rebuild(summarize=False)
        a_cluster = await _cluster_with(two_themes["A"][0])
        doc_id = await self._new_doc_near(store, 0)

        joined = await ClusterService.assign_document(DOC_TYPE_INCIDENT, doc_id)

        assert joined == [str(a_cluster.id)]
        a_cluster = await Cluster.get(a_cluster.id, fetch_links=False)
        key = member_key(DOC_TYPE_INCIDENT, doc_id)
        assert key in a_cluster.member_keys()
        assert a_cluster.member_scores[key] > 0.9
        assert a_cluster.summary_stale
        b_cluster = await _cluster_with(two_themes["B"][0])
        assert key not in b_cluster.member_keys()

    async def test_far_document_joins_nothing(self, test_db, store, two_themes):
        await ClusterService.rebuild(summarize=False)
        doc_id = await self._new_doc_near(store, 12)

        assert await ClusterService.assign_document(DOC_TYPE_INCIDENT, doc_id) == []

    async def test_respects_user_exclusion(self, test_db, store, two_themes):
        await ClusterService.rebuild(summarize=False)
        cluster = await _cluster_with(two_themes["A"][0])
        doc_id = await self._new_doc_near(store, 0)
        cluster.excluded_ids.append(member_key(DOC_TYPE_INCIDENT, doc_id))
        await cluster.save()

        assert await ClusterService.assign_document(DOC_TYPE_INCIDENT, doc_id) == []

    async def test_skips_user_and_archived_clusters(self, test_db, store, two_themes):
        user = await ClusterService.create(
            title="Mine", members=[(DOC_TYPE_INCIDENT, two_themes["A"][0])]
        )
        archived = Cluster(origin="auto", status="archived")
        await archived.insert()
        store.put(DOC_TYPE_CLUSTER, str(archived.id), _unit(0))
        doc_id = await self._new_doc_near(store, 0)

        assert await ClusterService.assign_document(DOC_TYPE_INCIDENT, doc_id) == []
        user = await Cluster.get(user.id, fetch_links=False)
        assert member_key(DOC_TYPE_INCIDENT, doc_id) not in user.member_keys()

    async def test_reassigning_unchanged_document_does_not_save(
        self, test_db, store, two_themes
    ):
        await ClusterService.rebuild(summarize=False)
        doc_id = await self._new_doc_near(store, 0)
        await ClusterService.assign_document(DOC_TYPE_INCIDENT, doc_id)
        cluster = await _cluster_with(doc_id)
        version = cluster.version

        assert await ClusterService.assign_document(DOC_TYPE_INCIDENT, doc_id) == []
        cluster = await Cluster.get(cluster.id, fetch_links=False)
        assert cluster.version == version

    async def test_unindexed_document_is_a_no_op(self, test_db, store, two_themes):
        await ClusterService.rebuild(summarize=False)
        missing = str(PydanticObjectId())

        assert await ClusterService.assign_document(DOC_TYPE_INCIDENT, missing) == []

    async def test_safe_wrapper_swallows_errors(self, test_db, store):
        async def boom(*args, **kwargs):
            raise RuntimeError("qdrant down")

        with patch.object(store, "get_document_vector", boom):
            await ClusterService.assign_document_safe(DOC_TYPE_INCIDENT, "x")


# ── Status, deletion and summaries ─────────────────────────────────


@pytest.mark.unit
class TestStatusAndCleanup:
    async def test_archive_drops_centroid_and_restore_brings_it_back(
        self, test_db, store, two_themes
    ):
        await ClusterService.rebuild(summarize=False)
        cluster = await _cluster_with(two_themes["A"][0])
        point = (DOC_TYPE_CLUSTER, str(cluster.id))

        await ClusterService.set_status(cluster, "archived")
        assert cluster.status == "archived"
        assert point not in store.vectors

        await ClusterService.set_status(cluster, "active")
        assert cluster.status == "active"
        assert point in store.vectors

    async def test_remove_document_everywhere(self, test_db, store, two_themes):
        await ClusterService.rebuild(summarize=False)
        doc_id = two_themes["A"][0]
        cluster = await _cluster_with(doc_id)
        cluster.summary_stale = False
        await cluster.save()

        await ClusterService.remove_document_everywhere(DOC_TYPE_INCIDENT, doc_id)

        cluster = await Cluster.get(cluster.id, fetch_links=False)
        key = member_key(DOC_TYPE_INCIDENT, doc_id)
        assert key not in cluster.member_keys()
        assert key not in cluster.member_scores
        assert cluster.summary_stale


@pytest.mark.unit
class TestSummaries:
    async def _cluster_of_real_incidents(self, **cluster_fields) -> Cluster:
        cluster = Cluster(**cluster_fields)
        for i in range(3):
            incident = make_incident(
                extracted_information=make_extracted_data(
                    description=f"Trawler seized for illegal cod fishing #{i}"
                )
            )
            await incident.insert()
            cluster.add_member(DOC_TYPE_INCIDENT, str(incident.id), score=0.9)
        await cluster.insert()
        return cluster

    async def test_auto_cluster_gets_generated_title(self, test_db):
        cluster = await self._cluster_of_real_incidents(origin="auto")

        await ClusterService.summarize(cluster, _stub_summarizer)

        assert cluster.title == "Generated title"
        assert cluster.summary == "Generated from 3 members."
        assert cluster.keywords == ["cod", "trawling"]
        assert not cluster.summary_stale

    async def test_locked_title_is_kept(self, test_db):
        cluster = await self._cluster_of_real_incidents(
            origin="auto", title="Palk Strait incursions", title_locked=True
        )

        await ClusterService.summarize(cluster, _stub_summarizer)

        assert cluster.title == "Palk Strait incursions"
        assert cluster.summary == "Generated from 3 members."

    async def test_summarize_stale_only_touches_stale_active(self, test_db):
        stale = await self._cluster_of_real_incidents(origin="auto")
        fresh = await self._cluster_of_real_incidents(origin="auto")
        fresh.summary_stale = False
        await fresh.save()
        archived = await self._cluster_of_real_incidents(
            origin="auto", status="archived"
        )

        stats = await ClusterService.summarize_stale(_stub_summarizer)

        assert stats == {"stale": 1, "summarized": 1, "failed": 0}
        assert (await Cluster.get(stale.id)).title == "Generated title"
        assert (await Cluster.get(fresh.id)).title == "Untitled cluster"
        assert (await Cluster.get(archived.id)).title == "Untitled cluster"


# ── Routes ─────────────────────────────────────────────────────────


@pytest.fixture
def as_user(sample_user):
    app.dependency_overrides[get_current_user] = lambda: sample_user
    yield sample_user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.unit
class TestClusterRoutes:
    async def test_list_clusters(self, async_client, store, two_themes):
        await ClusterService.rebuild(summarize=False)

        response = await async_client.get("/api/clusters")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert {c["member_count"] for c in body["clusters"]} == {6}

    async def test_put_title_locks_it(self, async_client, as_user, store, two_themes):
        await ClusterService.rebuild(summarize=False)
        cluster = await _cluster_with(two_themes["A"][0])

        response = await async_client.put(
            f"/api/clusters/{cluster.id}", json={"title": "Cod disputes"}
        )

        assert response.status_code == 200
        assert response.json()["title"] == "Cod disputes"
        assert response.json()["title_locked"] is True

    async def test_put_archive_drops_centroid(
        self, async_client, as_user, store, two_themes
    ):
        await ClusterService.rebuild(summarize=False)
        cluster = await _cluster_with(two_themes["A"][0])

        response = await async_client.put(
            f"/api/clusters/{cluster.id}", json={"status": "archived"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "archived"
        assert (DOC_TYPE_CLUSTER, str(cluster.id)) not in store.vectors

    async def test_add_and_remove_member(
        self, async_client, as_user, store, two_themes
    ):
        await ClusterService.rebuild(summarize=False)
        cluster = await _cluster_with(two_themes["A"][0])
        incident = make_incident()
        await incident.insert()
        store.put(DOC_TYPE_INCIDENT, str(incident.id), _unit(0))

        added = await async_client.post(
            f"/api/clusters/{cluster.id}/members",
            json={"doc_type": "incident", "doc_id": str(incident.id)},
        )
        assert added.status_code == 200
        assert str(incident.id) in added.json()["incident_ids"]

        removed = await async_client.delete(
            f"/api/clusters/{cluster.id}/members/incident/{incident.id}"
        )
        assert removed.status_code == 200
        assert str(incident.id) not in removed.json()["incident_ids"]
        assert f"incident:{incident.id}" in removed.json()["excluded_ids"]

    async def test_add_missing_member_is_404(
        self, async_client, as_user, store, two_themes
    ):
        await ClusterService.rebuild(summarize=False)
        cluster = await _cluster_with(two_themes["A"][0])

        response = await async_client.post(
            f"/api/clusters/{cluster.id}/members",
            json={"doc_type": "overview", "doc_id": str(PydanticObjectId())},
        )

        assert response.status_code == 404


@pytest.mark.unit
class TestDocumentIndexHooks:
    async def test_assignment_runs_only_for_reembedded_documents(self):
        from types import SimpleNamespace

        from app.rag import document_index

        calls = []

        async def fake_index(incidents, force):
            return ["changed-id"]

        async def fake_assign(doc_type, doc_id):
            calls.append((doc_type, doc_id))

        with (
            patch.object(document_index, "_index_incidents", fake_index),
            patch.object(ClusterService, "assign_document_safe", fake_assign),
        ):
            n = await document_index.index_and_assign_incidents(
                [SimpleNamespace(id="changed-id"), SimpleNamespace(id="same-id")]
            )

        assert n == 1
        assert calls == [(DOC_TYPE_INCIDENT, "changed-id")]

    async def test_overview_not_reindexed_is_not_assigned(self):
        from types import SimpleNamespace

        from app.rag import document_index

        calls = []

        async def fake_assign(doc_type, doc_id):
            calls.append((doc_type, doc_id))

        async def not_indexed(overview, force=False):
            return False

        with (
            patch.object(document_index, "index_overview", not_indexed),
            patch.object(ClusterService, "assign_document_safe", fake_assign),
        ):
            ok = await document_index.index_and_assign_overview(
                SimpleNamespace(id="ov")
            )

        assert ok is False
        assert calls == []
