"""Pure clustering logic: no database or network access, so it is unit-testable.

1. **Core clusters**: HDBSCAN over L2-normalised document vectors. Euclidean
   distance on unit vectors is monotonic with cosine distance, so this is
   cosine clustering using sklearn's fast tree-based neighbour search.
2. **Overlap**: HDBSCAN assigns each point to at most one cluster. Themes
   overlap (a cod incident on the India / Sri Lanka border belongs to both a
   "cod" and a "border dispute" cluster), so after finding the cores every
   document whose cosine similarity to a cluster's centroid is at least
   ``membership_threshold`` is added to that cluster too, including HDBSCAN
   noise points.
3. **Reconciliation**: proposed clusters are matched to the existing automatic
   clusters by member-set Jaccard overlap so cluster ids, titles and summaries
   stay stable across rebuilds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

DEFAULT_MIN_CLUSTER_SIZE = 3
DEFAULT_MEMBERSHIP_THRESHOLD = 0.75
DEFAULT_MATCH_JACCARD = 0.5


@dataclass
class ProposedCluster:
    """A cluster found by :func:`find_clusters`."""

    scores: dict[str, float]  # member_key -> cosine similarity to centroid
    centroid: list[float]
    core_size: int

    @property
    def members(self) -> set[str]:
        return set(self.scores)


@dataclass
class ExistingCluster:
    """The parts of a stored cluster that reconciliation needs."""

    id: str
    members: set[str]
    excluded: set[str] = field(default_factory=set)


@dataclass
class ReconcilePlan:
    updates: list[tuple[str, ProposedCluster]]  # (existing id, proposal)
    creates: list[ProposedCluster]
    archives: list[str]  # existing ids no longer found


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def centroid_of(vectors: np.ndarray) -> np.ndarray:
    """Unit-length mean direction of a set of (normalised) vectors."""
    mean = vectors.mean(axis=0)
    norm = np.linalg.norm(mean)
    return mean / norm if norm else mean


def find_clusters(
    keys: Sequence[str],
    vectors: np.ndarray | Sequence[Sequence[float]],
    *,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    min_samples: int | None = None,
    membership_threshold: float = DEFAULT_MEMBERSHIP_THRESHOLD,
) -> list[ProposedCluster]:
    """Cluster documents; a document may appear in several clusters.

    ``keys`` are member keys (``"incident:<id>"``) aligned with ``vectors``.
    """
    from sklearn.cluster import HDBSCAN

    if len(keys) < max(2, min_cluster_size):
        return []

    matrix = normalize_rows(np.asarray(vectors, dtype=np.float64))
    labels = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        copy=True,
    ).fit_predict(matrix)

    proposals = []
    for label in sorted(set(labels) - {-1}):
        core_idx = np.flatnonzero(labels == label)
        centroid = centroid_of(matrix[core_idx])
        sims = matrix @ centroid

        member_idx = set(core_idx.tolist()) | set(
            np.flatnonzero(sims >= membership_threshold).tolist()
        )
        proposals.append(
            ProposedCluster(
                scores={keys[i]: float(sims[i]) for i in sorted(member_idx)},
                centroid=centroid.tolist(),
                core_size=len(core_idx),
            )
        )
    return proposals


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def reconcile(
    proposals: Sequence[ProposedCluster],
    existing: Sequence[ExistingCluster],
    *,
    match_jaccard: float = DEFAULT_MATCH_JACCARD,
) -> ReconcilePlan:
    """Match proposals to existing automatic clusters (greedy, best overlap first).

    Exclusions are taken into account when comparing, so a cluster the user
    pruned still matches the proposal it came from.
    """
    pairs = []
    for p_idx, proposal in enumerate(proposals):
        for e_idx, cluster in enumerate(existing):
            score = jaccard(proposal.members - cluster.excluded, cluster.members)
            if score >= match_jaccard:
                pairs.append((score, p_idx, e_idx))
    pairs.sort(reverse=True)

    matched_p: set[int] = set()
    matched_e: set[int] = set()
    updates = []
    for _, p_idx, e_idx in pairs:
        if p_idx in matched_p or e_idx in matched_e:
            continue
        matched_p.add(p_idx)
        matched_e.add(e_idx)
        updates.append((existing[e_idx].id, proposals[p_idx]))

    return ReconcilePlan(
        updates=updates,
        creates=[p for i, p in enumerate(proposals) if i not in matched_p],
        archives=[c.id for i, c in enumerate(existing) if i not in matched_e],
    )
