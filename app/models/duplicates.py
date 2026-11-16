"""Stored candidate duplicate pairs of incidents, awaiting human review."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

DuplicateStatus = Literal["pending", "duplicate", "not_duplicate", "merged"]


def ordered_pair(
    a: PydanticObjectId, b: PydanticObjectId
) -> tuple[PydanticObjectId, PydanticObjectId]:
    """Canonical (lower, higher) ordering so each pair is stored once."""
    return (a, b) if str(a) <= str(b) else (b, a)


class DuplicateCandidate(Document):
    """A pair of incidents that may describe the same event.

    Incident ids are stored as plain ObjectIds (not ``Link``) in canonical
    order, which keeps the unique pair index and "all pairs for incident X"
    queries simple. This is machine-generated review state, so it is not an
    ``AuditedDocument``; the reviewer is recorded directly.
    """

    incident_a_id: PydanticObjectId
    incident_b_id: PydanticObjectId

    vector_score: float | None = None
    kde_scores: dict[str, float | None] = Field(default_factory=dict)
    combined_score: float = 0.0
    coverage: float = Field(
        default=0.0,
        description="Share of scoring weight with data on both incidents. Low "
        "coverage means the score leans mostly on the vector similarity.",
    )
    shares_source: bool = Field(
        default=False,
        description="Both incidents were extracted from at least one common source.",
    )

    status: DuplicateStatus = "pending"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None

    scored_with: str = Field(description="Scoring scheme version (SCORING_VERSION)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "duplicate_candidates"
        indexes = [
            IndexModel(
                [("incident_a_id", ASCENDING), ("incident_b_id", ASCENDING)],
                unique=True,
            ),
            IndexModel([("incident_b_id", ASCENDING)]),
            IndexModel([("status", ASCENDING), ("combined_score", DESCENDING)]),
        ]
