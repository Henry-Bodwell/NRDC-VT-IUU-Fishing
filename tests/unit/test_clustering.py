"""Unit tests for clustering: the pure engine and Cluster membership helpers."""

import numpy as np
import pytest
from beanie import PydanticObjectId

from app.clustering.engine import (
    ExistingCluster,
    ProposedCluster,
    find_clusters,
    jaccard,
    reconcile,
)
from app.models.clusters import Cluster, link_id, member_key


def _blob(center: np.ndarray, n: int, rng, noise: float = 0.02) -> np.ndarray:
    return center + rng.normal(scale=noise, size=(n, center.shape[0]))


@pytest.fixture
def two_themes():
    """Two tight blobs plus one point between them and one far-away outlier."""
    rng = np.random.default_rng(0)
    dim = 16
    a = np.zeros(dim)
    a[0] = 1.0
    b = np.zeros(dim)
    b[1] = 1.0
    bridge = (a + b) / np.linalg.norm(a + b)
    outlier = np.zeros(dim)
    outlier[5] = 1.0

    vectors = np.vstack(
        [_blob(a, 8, rng), _blob(b, 8, rng), bridge[None, :], outlier[None, :]]
    )
    keys = (
        [f"incident:a{i}" for i in range(8)]
        + [f"incident:b{i}" for i in range(8)]
        + ["incident:bridge", "overview:outlier"]
    )
    return keys, vectors


@pytest.mark.unit
class TestFindClusters:
    def test_finds_both_themes(self, two_themes):
        keys, vectors = two_themes
        clusters = find_clusters(keys, vectors, min_cluster_size=3)
        member_sets = [c.members for c in clusters]
        assert any({f"incident:a{i}" for i in range(8)} <= m for m in member_sets)
        assert any({f"incident:b{i}" for i in range(8)} <= m for m in member_sets)

    def test_bridge_point_joins_both_clusters(self, two_themes):
        keys, vectors = two_themes
        clusters = find_clusters(
            keys, vectors, min_cluster_size=3, membership_threshold=0.65
        )
        assert sum("incident:bridge" in c.members for c in clusters) == 2

    def test_outlier_joins_nothing(self, two_themes):
        keys, vectors = two_themes
        clusters = find_clusters(keys, vectors, min_cluster_size=3)
        assert all("overview:outlier" not in c.members for c in clusters)

    def test_scores_are_centroid_similarity(self, two_themes):
        keys, vectors = two_themes
        for cluster in find_clusters(keys, vectors, min_cluster_size=3):
            assert all(-1.0 <= s <= 1.0 for s in cluster.scores.values())
            assert np.linalg.norm(cluster.centroid) == pytest.approx(1.0)

    def test_too_few_documents(self):
        assert find_clusters(["incident:a"], [[1.0, 0.0]], min_cluster_size=3) == []


def _proposal(*members: str) -> ProposedCluster:
    return ProposedCluster(
        scores={m: 0.9 for m in members}, centroid=[1.0], core_size=len(members)
    )


@pytest.mark.unit
class TestReconcile:
    def test_jaccard(self):
        assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
        assert jaccard(set(), set()) == 0.0

    def test_matches_keep_ids_and_new_ones_are_created(self):
        existing = [ExistingCluster(id="c1", members={"x", "y", "z"})]
        plan = reconcile(
            [_proposal("x", "y", "z", "w"), _proposal("p", "q", "r")], existing
        )
        assert [(cid, p.members) for cid, p in plan.updates] == [
            ("c1", {"x", "y", "z", "w"})
        ]
        assert [p.members for p in plan.creates] == [{"p", "q", "r"}]
        assert plan.archives == []

    def test_unmatched_existing_is_archived(self):
        existing = [ExistingCluster(id="old", members={"a", "b", "c"})]
        plan = reconcile([_proposal("x", "y", "z")], existing)
        assert plan.archives == ["old"]
        assert len(plan.creates) == 1

    def test_exclusions_do_not_break_matching(self):
        # User removed "d" from a 4-member cluster; the proposal still has it.
        existing = [ExistingCluster(id="c1", members={"a", "b", "c"}, excluded={"d"})]
        plan = reconcile([_proposal("a", "b", "c", "d")], existing, match_jaccard=0.9)
        assert [cid for cid, _ in plan.updates] == ["c1"]

    def test_each_existing_matched_at_most_once(self):
        existing = [ExistingCluster(id="c1", members={"a", "b", "c", "d"})]
        plan = reconcile(
            [_proposal("a", "b", "c"), _proposal("a", "b", "c", "d")], existing
        )
        assert [(cid, p.members) for cid, p in plan.updates] == [
            ("c1", {"a", "b", "c", "d"})
        ]
        assert len(plan.creates) == 1


def _cluster(**kw) -> Cluster:
    # model_construct skips Beanie's collection check (no database in unit tests).
    return Cluster.model_construct(**kw)


@pytest.mark.unit
class TestClusterMembership:
    def test_add_member_and_keys(self):
        cluster = _cluster()
        oid = str(PydanticObjectId())
        assert cluster.add_member("incident", oid, score=0.91234)
        assert not cluster.add_member("incident", oid)
        assert cluster.member_keys() == {member_key("incident", oid)}
        assert link_id(cluster.incidents[0]) == oid
        assert cluster.member_scores[member_key("incident", oid)] == 0.9123
        assert cluster.summary_stale

    def test_remove_member_records_exclusion(self):
        cluster = _cluster()
        oid = str(PydanticObjectId())
        cluster.add_member("overview", oid)
        cluster.summary_stale = False

        assert cluster.remove_member("overview", oid)
        assert cluster.overviews == []
        assert cluster.excluded_ids == [member_key("overview", oid)]
        assert cluster.summary_stale

    def test_re_adding_lifts_exclusion(self):
        cluster = _cluster()
        oid = str(PydanticObjectId())
        cluster.add_member("incident", oid)
        cluster.remove_member("incident", oid)
        cluster.add_member("incident", oid)
        assert cluster.excluded_ids == []

    def test_set_members_respects_exclusions_and_reports_change(self):
        keep, dropped = str(PydanticObjectId()), str(PydanticObjectId())
        cluster = _cluster(excluded_ids=[member_key("incident", dropped)])
        cluster.summary_stale = False

        changed = cluster.set_members(
            {member_key("incident", keep): 0.8, member_key("incident", dropped): 0.9}
        )
        assert changed
        assert cluster.member_keys() == {member_key("incident", keep)}
        assert cluster.summary_stale

        cluster.summary_stale = False
        assert not cluster.set_members({member_key("incident", keep): 0.85})
        assert not cluster.summary_stale
        assert cluster.member_scores == {member_key("incident", keep): 0.85}
