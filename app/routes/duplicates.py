"""Similarity search and duplicate-candidate review endpoints."""

import logging
from typing import Literal, Optional

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from pymongo import DESCENDING

from app.auth import get_current_admin_user, get_current_user
from app.models.duplicates import DuplicateCandidate
from app.models.incidents import IncidentReport, IndustryOverview
from app.models.task import TaskStatus
from app.models.users import User
from app.rag.vector_store import (
    DOC_TYPE_INCIDENT,
    DOC_TYPE_OVERVIEW,
    DocumentHit,
    get_document_store,
)
from app.routes.helpers import valid_object_id
from app.service.dedup_service import DEFAULT_K, DEFAULT_MIN_VECTOR, DedupService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["similarity"])


class DuplicateReviewRequest(BaseModel):
    status: Literal["pending", "duplicate", "not_duplicate"]
    note: Optional[str] = None


async def _describe_hits(hits: list[DocumentHit]) -> list[dict]:
    """Attach a short label (description / summary) to each search hit."""
    ids = {
        doc_type: [
            PydanticObjectId(h.doc_id)
            for h in hits
            if h.doc_type == doc_type and PydanticObjectId.is_valid(h.doc_id)
        ]
        for doc_type in (DOC_TYPE_INCIDENT, DOC_TYPE_OVERVIEW)
    }
    labels: dict[tuple[str, str], str] = {}
    if ids[DOC_TYPE_INCIDENT]:
        for incident in await IncidentReport.find(
            In(IncidentReport.id, ids[DOC_TYPE_INCIDENT])
        ).to_list():
            labels[(DOC_TYPE_INCIDENT, str(incident.id))] = (
                incident.extracted_information.description
            )
    if ids[DOC_TYPE_OVERVIEW]:
        for overview in await IndustryOverview.find(
            In(IndustryOverview.id, ids[DOC_TYPE_OVERVIEW])
        ).to_list():
            labels[(DOC_TYPE_OVERVIEW, str(overview.id))] = (
                overview.extracted_information.summary
            )

    return [
        {
            "doc_type": h.doc_type,
            "doc_id": h.doc_id,
            "score": round(h.score, 4),
            "label": labels.get((h.doc_type, h.doc_id)),
        }
        for h in hits
        # Drop stale vectors whose document no longer exists.
        if (h.doc_type, h.doc_id) in labels
    ]


async def _similar(
    doc_type: str, doc_id: str, k: int, min_score: float | None, types: list[str]
) -> dict:
    try:
        hits = await get_document_store().similar_to_document(
            doc_type, doc_id, k=k, doc_types=types, score_threshold=min_score
        )
    except Exception as e:
        logger.error(f"Similarity search failed for {doc_type}:{doc_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store unavailable",
        )
    return {
        "doc_type": doc_type,
        "doc_id": doc_id,
        "results": await _describe_hits(hits),
    }


def _types(include: Literal["all", "incidents", "overviews"]) -> list[str]:
    return {
        "all": [DOC_TYPE_INCIDENT, DOC_TYPE_OVERVIEW],
        "incidents": [DOC_TYPE_INCIDENT],
        "overviews": [DOC_TYPE_OVERVIEW],
    }[include]


@router.get("/incidents/{report_id}/similar")
async def similar_to_incident(
    report_id: str,
    k: int = Query(10, ge=1, le=100),
    min_score: Optional[float] = Query(None, ge=-1.0, le=1.0),
    include: Literal["all", "incidents", "overviews"] = "all",
):
    """Nearest incidents/overviews to an incident by document vector."""
    valid_object_id(report_id)
    return await _similar(DOC_TYPE_INCIDENT, report_id, k, min_score, _types(include))


@router.get("/overviews/{overview_id}/similar")
async def similar_to_overview(
    overview_id: str,
    k: int = Query(10, ge=1, le=100),
    min_score: Optional[float] = Query(None, ge=-1.0, le=1.0),
    include: Literal["all", "incidents", "overviews"] = "all",
):
    """Nearest incidents/overviews to an industry overview by document vector."""
    valid_object_id(overview_id)
    return await _similar(DOC_TYPE_OVERVIEW, overview_id, k, min_score, _types(include))


@router.get("/duplicates")
async def list_duplicates(
    status_filter: Optional[
        Literal["pending", "duplicate", "not_duplicate", "merged"]
    ] = Query("pending", alias="status"),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    include_shared_source: bool = False,
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
):
    """Candidate duplicate pairs, highest combined score first.

    Pairs extracted from a common source are hidden by default: segmentation
    already split those apart deliberately.
    """
    query: dict = {"combined_score": {"$gte": min_score}}
    if status_filter:
        query["status"] = status_filter
    if not include_shared_source:
        query["shares_source"] = False

    candidates = (
        await DuplicateCandidate.find(query)
        .sort([("combined_score", DESCENDING)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    total = await DuplicateCandidate.find(query).count()
    return {
        "total": total,
        "candidates": [c.model_dump(mode="json") for c in candidates],
    }


@router.get("/duplicates/compare")
async def compare_incidents(
    a: str,
    b: str,
    current_user: User = Depends(get_current_user),
):
    """Score any two incidents side by side without storing the result."""
    valid_object_id(a)
    valid_object_id(b)
    try:
        return await DedupService.compare(a, b)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/duplicates/scan", status_code=status.HTTP_202_ACCEPTED)
async def scan_duplicates(
    background_tasks: BackgroundTasks,
    k: int = Query(DEFAULT_K, ge=1, le=100),
    min_vector: float = Query(DEFAULT_MIN_VECTOR, ge=0.0, le=1.0),
    current_user: User = Depends(get_current_admin_user),
):
    """Run duplicate detection across all incidents as a background task."""
    task = TaskStatus(
        task_type="duplicate_scan",
        user_id=str(current_user.id),
        input_params={"k": k, "min_vector": min_vector},
    )
    await task.insert()

    async def run():
        async def progress(stage: str, percent: int):
            await task.update_progress(stage, percent)

        try:
            await task.update_progress("scanning", 0)
            result = await DedupService.scan_all(
                k=k, min_vector=min_vector, progress_callback=progress
            )
            await task.mark_completed(result)
        except Exception as e:
            logger.error(f"Duplicate scan task {task.task_id} failed: {e}")
            await task.mark_failed(str(e))

    background_tasks.add_task(run)
    return {"task_id": task.task_id}


@router.get("/duplicates/{candidate_id}")
async def get_duplicate(
    candidate_id: str,
    current_user: User = Depends(get_current_user),
):
    """A candidate pair with both incidents' KDEs side by side."""
    valid_object_id(candidate_id)
    candidate = await DuplicateCandidate.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Duplicate candidate not found")
    return await DedupService.candidate_detail(candidate)


@router.patch("/duplicates/{candidate_id}")
async def review_duplicate(
    candidate_id: str,
    body: DuplicateReviewRequest,
    current_user: User = Depends(get_current_user),
):
    """Record a reviewer's verdict on a candidate pair."""
    valid_object_id(candidate_id)
    candidate = await DedupService.review(
        candidate_id, body.status, str(current_user.id), body.note
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Duplicate candidate not found")
    return candidate.model_dump(mode="json")
