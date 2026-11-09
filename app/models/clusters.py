"""Clusters of related incidents and industry overviews (e.g. a species, a
region, an ongoing dispute) with a generated summary.

Membership is many-to-many: an incident can sit in any number of clusters.
Links are stored only on the Cluster; "which clusters is this incident in?" is
answered via the multikey indexes on ``incidents.$id`` / ``overviews.$id``.
Keeping the links one-directional means a clustering rebuild never writes to
(and never creates audit entries on) the member incidents themselves.

Always change membership through :meth:`Cluster.add_member` /
:meth:`Cluster.remove_member` so ``member_scores`` and ``excluded_ids`` stay
consistent.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal

from beanie import Link
from bson import DBRef
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.audit.base import AuditedDocument
from app.models.incidents import IncidentReport
from app.models.overviews import IndustryOverview

MemberType = Literal["incident", "overview"]


def member_key(doc_type: str, doc_id: str) -> str:
    """Key used in ``member_scores`` / ``excluded_ids``: ``"incident:<id>"``."""
    return f"{doc_type}:{doc_id}"


def link_id(link) -> str:
    """Id of a Link or a fetched document, as a string."""
    ref = getattr(link, "ref", None)
    return str(ref.id if ref is not None else link.id)


def make_link(doc_type: str, doc_id) -> Link:
    """Build an unfetched Link without loading the member document."""
    from beanie import PydanticObjectId

    model = IncidentReport if doc_type == "incident" else IndustryOverview
    collection = model.Settings.name
    return Link(DBRef(collection, PydanticObjectId(doc_id)), model)


class Cluster(AuditedDocument):
    """A group of related incidents/overviews with a generated summary."""

    title: str = Field(default="Untitled cluster")
    summary: str | None = None
    keywords: List[str] = Field(default_factory=list)

    incidents: List[Link[IncidentReport]] = Field(default_factory=list)
    overviews: List[Link[IndustryOverview]] = Field(default_factory=list)

    member_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Cosine similarity of each member to the cluster centroid, "
        "keyed by member_key().",
    )
    excluded_ids: List[str] = Field(
        default_factory=list,
        description="member_key()s a user removed; rebuilds never re-add them.",
    )

    origin: Literal["auto", "user"] = "auto"
    status: Literal["active", "archived"] = "active"

    summary_stale: bool = True
    summary_generated_at: datetime | None = None

    class Settings:
        name = "clusters"
        max_nesting_depth = 1
        indexes = [
            IndexModel([("incidents.$id", ASCENDING)]),
            IndexModel([("overviews.$id", ASCENDING)]),
            IndexModel([("status", ASCENDING), ("origin", ASCENDING)]),
        ]

    # ── Membership helpers ─────────────────────────────────────────

    def member_keys(self) -> set[str]:
        return {member_key("incident", link_id(i)) for i in self.incidents} | {
            member_key("overview", link_id(o)) for o in self.overviews
        }

    def _members_list(self, doc_type: str) -> list:
        return self.incidents if doc_type == "incident" else self.overviews

    def add_member(
        self, doc_type: str, doc_id: str, score: float | None = None
    ) -> bool:
        """Add a member (in memory). Returns False if it was already present.

        Explicitly adding a member also lifts any earlier user exclusion.
        """
        key = member_key(doc_type, doc_id)
        self.excluded_ids = [k for k in self.excluded_ids if k != key]
        if score is not None:
            self.member_scores[key] = round(float(score), 4)
        if key in self.member_keys():
            return False
        self._members_list(doc_type).append(make_link(doc_type, doc_id))
        self.summary_stale = True
        return True

    def remove_member(self, doc_type: str, doc_id: str, exclude: bool = True) -> bool:
        """Remove a member (in memory). Returns False if it was not present.

        ``exclude=True`` records the removal so automatic rebuilds respect it.
        """
        key = member_key(doc_type, doc_id)
        members = self._members_list(doc_type)
        kept = [m for m in members if link_id(m) != str(doc_id)]
        removed = len(kept) != len(members)
        if doc_type == "incident":
            self.incidents = kept
        else:
            self.overviews = kept
        self.member_scores.pop(key, None)
        if exclude and key not in self.excluded_ids:
            self.excluded_ids.append(key)
        if removed:
            self.summary_stale = True
        return removed

    def set_members(self, scores: dict[str, float]) -> bool:
        """Replace membership with ``{member_key: score}`` (minus exclusions).

        Returns True if the member set changed (scores alone do not count).
        """
        excluded = set(self.excluded_ids)
        wanted = {k: v for k, v in scores.items() if k not in excluded}
        changed = set(wanted) != self.member_keys()

        incidents, overviews = [], []
        for key in sorted(wanted):
            doc_type, doc_id = key.split(":", 1)
            target = incidents if doc_type == "incident" else overviews
            target.append(make_link(doc_type, doc_id))
        self.incidents = incidents
        self.overviews = overviews
        self.member_scores = {k: round(float(v), 4) for k, v in wanted.items()}
        if changed:
            self.summary_stale = True
        return changed
