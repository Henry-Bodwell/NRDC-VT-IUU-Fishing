"""Duplicate detection for incidents: vector neighbours + KDE comparison."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from beanie import PydanticObjectId
from beanie.operators import In, Or
from pymongo.errors import DuplicateKeyError

from app.dedup.kde_compare import SCORING_VERSION, extract_kdes, score_pair
from app.models.duplicates import DuplicateCandidate, DuplicateStatus, ordered_pair
from app.models.incidents import IncidentReport
from app.rag.document_index import index_incident
from app.rag.vector_store import DOC_TYPE_INCIDENT, get_document_store

logger = logging.getLogger(__name__)

DEFAULT_K = 10
DEFAULT_MIN_VECTOR = 0.80


def _source_ids(incident: IncidentReport) -> set[str]:
    ids = set()
    for source in incident.sources or []:
        ref = getattr(source, "ref", None)
        ids.add(str(ref.id if ref is not None else source.id))
    return ids


class DedupService:
    """Find, store and review candidate duplicate incident pairs."""

    @staticmethod
    async def upsert_candidate(
        incident: IncidentReport,
        other: IncidentReport,
        vector_score: float | None,
    ) -> DuplicateCandidate:
        """Score a pair and store it, preserving any existing review status."""
        score = score_pair(incident, other, vector_score)
        a_id, b_id = ordered_pair(incident.id, other.id)
        shares_source = bool(_source_ids(incident) & _source_ids(other))

        fields = {
            "vector_score": score.vector_score,
            "kde_scores": score.kde_scores,
            "combined_score": score.combined,
            "coverage": score.coverage,
            "shares_source": shares_source,
            "scored_with": SCORING_VERSION,
            "updated_at": datetime.utcnow(),
        }

        existing = await DuplicateCandidate.find_one(
            DuplicateCandidate.incident_a_id == a_id,
            DuplicateCandidate.incident_b_id == b_id,
        )
        if existing is None:
            candidate = DuplicateCandidate(
                incident_a_id=a_id, incident_b_id=b_id, **fields
            )
            try:
                await candidate.insert()
                return candidate
            except DuplicateKeyError:
                # Inserted concurrently (e.g. both incidents scanned at once).
                existing = await DuplicateCandidate.find_one(
                    DuplicateCandidate.incident_a_id == a_id,
                    DuplicateCandidate.incident_b_id == b_id,
                )
                if existing is None:
                    raise

        for key, value in fields.items():
            setattr(existing, key, value)
        await existing.save()
        return existing

    @staticmethod
    async def find_candidates(
        incident: IncidentReport,
        k: int = DEFAULT_K,
        min_vector: float = DEFAULT_MIN_VECTOR,
    ) -> list[DuplicateCandidate]:
        """Find the incident's nearest neighbours and store them as candidates.

        Indexes the incident first if it has no current vector. Returns the
        stored candidates (new or refreshed).
        """
        if incident.id is None:
            return []

        await index_incident(incident)
        hits = await get_document_store().similar_to_document(
            DOC_TYPE_INCIDENT,
            str(incident.id),
            k=k,
            doc_types=[DOC_TYPE_INCIDENT],
            score_threshold=min_vector,
        )
        if not hits:
            return []

        neighbour_ids = [
            PydanticObjectId(h.doc_id)
            for h in hits
            if PydanticObjectId.is_valid(h.doc_id)
        ]
        neighbours = {
            str(n.id): n
            for n in await IncidentReport.find(
                In(IncidentReport.id, neighbour_ids)
            ).to_list()
        }

        candidates = []
        for hit in hits:
            other = neighbours.get(hit.doc_id)
            if other is None:
                # Stale vector for a deleted incident.
                continue
            candidates.append(
                await DedupService.upsert_candidate(incident, other, hit.score)
            )
        return candidates

    @staticmethod
    async def find_candidates_safe(incident: IncidentReport) -> None:
        """Ingestion hook: run :meth:`find_candidates`, logging any failure."""
        try:
            found = await DedupService.find_candidates(incident)
            if found:
                logger.info(
                    f"Incident {incident.id}: {len(found)} duplicate candidate(s)"
                )
        except Exception as e:
            logger.warning(
                f"Duplicate detection failed for incident {incident.id}: {e}"
            )

    @staticmethod
    async def scan_all(
        k: int = DEFAULT_K,
        min_vector: float = DEFAULT_MIN_VECTOR,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> dict:
        """Run duplicate detection over every incident."""
        total = await IncidentReport.find_all().count()
        processed = failed = pairs = 0
        async for incident in IncidentReport.find_all():
            try:
                pairs += len(
                    await DedupService.find_candidates(
                        incident, k=k, min_vector=min_vector
                    )
                )
            except Exception as e:
                failed += 1
                logger.warning(f"Duplicate scan failed for {incident.id}: {e}")
            processed += 1
            if progress_callback and total and processed % 25 == 0:
                await progress_callback("scanning", int(100 * processed / total))
        return {
            "incidents": total,
            "processed": processed,
            "failed": failed,
            "candidate_hits": pairs,
        }

    @staticmethod
    async def compare(incident_a_id: str, incident_b_id: str) -> dict:
        """Ad-hoc comparison of two incidents (nothing is stored)."""
        a = await IncidentReport.get(incident_a_id)
        b = await IncidentReport.get(incident_b_id)
        if a is None or b is None:
            raise ValueError("Incident not found")
        vector_score = None
        store = get_document_store()
        va = await store.get_document_vector(DOC_TYPE_INCIDENT, str(a.id))
        vb = await store.get_document_vector(DOC_TYPE_INCIDENT, str(b.id))
        if va and vb:
            dot = sum(x * y for x, y in zip(va, vb))
            norm = (sum(x * x for x in va) ** 0.5) * (sum(y * y for y in vb) ** 0.5)
            vector_score = dot / norm if norm else None
        score = score_pair(a, b, vector_score)
        return {
            "incident_a": {"id": str(a.id), "kdes": extract_kdes(a).to_dict()},
            "incident_b": {"id": str(b.id), "kdes": extract_kdes(b).to_dict()},
            "vector_score": score.vector_score,
            "kde_scores": score.kde_scores,
            "combined_score": score.combined,
            "coverage": score.coverage,
        }

    @staticmethod
    async def candidate_detail(candidate: DuplicateCandidate) -> dict:
        """A candidate with both incidents' KDEs side by side."""
        a = await IncidentReport.get(candidate.incident_a_id)
        b = await IncidentReport.get(candidate.incident_b_id)

        def describe(incident: IncidentReport | None) -> dict | None:
            if incident is None:
                return None
            return {
                "id": str(incident.id),
                "description": incident.extracted_information.description,
                "verified": incident.verified,
                "kdes": extract_kdes(incident).to_dict(),
            }

        return {
            "candidate": candidate.model_dump(mode="json"),
            "incident_a": describe(a),
            "incident_b": describe(b),
        }

    @staticmethod
    async def review(
        candidate_id: str,
        status: DuplicateStatus,
        user_id: str,
        note: str | None = None,
    ) -> DuplicateCandidate | None:
        candidate = await DuplicateCandidate.get(candidate_id)
        if candidate is None:
            return None
        candidate.status = status
        candidate.reviewed_by = user_id
        candidate.reviewed_at = datetime.utcnow()
        candidate.review_note = note
        candidate.updated_at = datetime.utcnow()
        await candidate.save()
        return candidate

    @staticmethod
    async def remove_candidates_for(incident_id: PydanticObjectId) -> None:
        """Delete every candidate pair involving an incident (best-effort)."""
        try:
            await DuplicateCandidate.find(
                Or(
                    DuplicateCandidate.incident_a_id == incident_id,
                    DuplicateCandidate.incident_b_id == incident_id,
                )
            ).delete()
        except Exception as e:
            logger.warning(
                f"Could not remove duplicate candidates for {incident_id}: {e}"
            )
