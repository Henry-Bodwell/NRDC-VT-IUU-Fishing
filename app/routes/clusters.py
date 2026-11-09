"""Cluster endpoints: browse, curate, summarise and rebuild clusters."""

import logging
from typing import List, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from pydantic import BaseModel, Field
from pymongo import DESCENDING

from app.audit.context import AuditContext
from app.auth import get_current_admin_user, get_current_user
from app.clustering.engine import DEFAULT_MEMBERSHIP_THRESHOLD, DEFAULT_MIN_CLUSTER_SIZE
from app.models.clusters import Cluster, link_id
from app.models.task import TaskStatus
from app.models.users import User
from app.routes.helpers import valid_object_id
from app.service.cluster_service import ClusterService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["clusters"])

DocType = Literal["incident", "overview"]


class ClusterMember(BaseModel):
    doc_type: DocType
    doc_id: str


class ClusterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    members: List[ClusterMember] = Field(default_factory=list)


class ClusterUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    summary: Optional[str] = None
    keywords: Optional[List[str]] = None
    status: Optional[Literal["active", "archived"]] = None


def cluster_out(cluster: Cluster) -> dict:
    """Serialise a cluster with member ids instead of raw Link objects."""
    return {
        "id": str(cluster.id),
        "title": cluster.title,
        "summary": cluster.summary,
        "keywords": cluster.keywords,
        "origin": cluster.origin,
        "status": cluster.status,
        "incident_ids": [link_id(i) for i in cluster.incidents],
        "overview_ids": [link_id(o) for o in cluster.overviews],
        "member_count": len(cluster.incidents) + len(cluster.overviews),
        "member_scores": cluster.member_scores,
        "excluded_ids": cluster.excluded_ids,
        "summary_stale": cluster.summary_stale,
        "summary_generated_at": cluster.summary_generated_at,
        "created_at": cluster.created_at,
        "updated_at": cluster.updated_at,
        "version": cluster.version,
    }


async def _get_or_404(cluster_id: str) -> Cluster:
    valid_object_id(cluster_id)
    cluster = await ClusterService.get(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.get("/clusters")
async def list_clusters(
    status_filter: Optional[Literal["active", "archived"]] = Query(
        "active", alias="status"
    ),
    origin: Optional[Literal["auto", "user"]] = None,
    q: Optional[str] = Query(None, description="Case-insensitive title/keyword match"),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    query: dict = {}
    if status_filter:
        query["status"] = status_filter
    if origin:
        query["origin"] = origin
    if q:
        pattern = {"$regex": q, "$options": "i"}
        query["$or"] = [{"title": pattern}, {"keywords": pattern}]

    clusters = (
        await Cluster.find(query, fetch_links=False)
        .sort([("updated_at", DESCENDING)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    total = await Cluster.find(query).count()
    return {"total": total, "clusters": [cluster_out(c) for c in clusters]}


@router.post("/clusters", status_code=status.HTTP_201_CREATED)
async def create_cluster(
    body: ClusterCreate, current_user: User = Depends(get_current_user)
):
    """Create a user-curated cluster (never modified by automatic rebuilds)."""
    for member in body.members:
        valid_object_id(member.doc_id)
    with AuditContext.with_user(str(current_user.id)):
        cluster = await ClusterService.create(
            title=body.title,
            summary=body.summary,
            keywords=body.keywords,
            members=[(m.doc_type, m.doc_id) for m in body.members],
        )
    return cluster_out(cluster)


@router.post("/clusters/rebuild", status_code=status.HTTP_202_ACCEPTED)
async def rebuild_clusters(
    background_tasks: BackgroundTasks,
    min_cluster_size: int = Query(DEFAULT_MIN_CLUSTER_SIZE, ge=2, le=100),
    membership_threshold: float = Query(DEFAULT_MEMBERSHIP_THRESHOLD, ge=0.0, le=1.0),
    summarize: bool = True,
    current_user: User = Depends(get_current_admin_user),
):
    """Re-cluster all incidents/overviews as a background task."""
    params = {
        "min_cluster_size": min_cluster_size,
        "membership_threshold": membership_threshold,
        "summarize": summarize,
    }
    task = TaskStatus(
        task_type="cluster_rebuild",
        user_id=str(current_user.id),
        input_params=params,
    )
    await task.insert()

    async def run():
        async def progress(stage: str, percent: int):
            await task.update_progress(stage, percent)

        try:
            await task.update_progress("loading", 0)
            result = await ClusterService.rebuild(**params, progress_callback=progress)
            await task.mark_completed(result)
        except Exception as e:
            logger.error(f"Cluster rebuild task {task.task_id} failed: {e}")
            await task.mark_failed(str(e))

    background_tasks.add_task(run)
    return {"task_id": task.task_id}


@router.get("/clusters/{cluster_id}")
async def get_cluster(cluster_id: str, expand: bool = False):
    """A cluster; ``expand=true`` adds member labels, most central first."""
    cluster = await _get_or_404(cluster_id)
    out = cluster_out(cluster)
    if expand:
        out["members"] = await ClusterService.member_labels(cluster)
    return out


@router.put("/clusters/{cluster_id}")
async def update_cluster(
    cluster_id: str,
    body: ClusterUpdate,
    current_user: User = Depends(get_current_user),
):
    cluster = await _get_or_404(cluster_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cluster, field, value)
    with AuditContext.with_user(str(current_user.id)):
        await cluster.save()
    return cluster_out(cluster)


@router.delete(
    "/clusters/{cluster_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_cluster(
    cluster_id: str, current_user: User = Depends(get_current_admin_user)
):
    cluster = await _get_or_404(cluster_id)
    with AuditContext.with_user(str(current_user.id)):
        await ClusterService.delete(cluster)


@router.post("/clusters/{cluster_id}/members")
async def add_cluster_member(
    cluster_id: str,
    body: ClusterMember,
    current_user: User = Depends(get_current_user),
):
    cluster = await _get_or_404(cluster_id)
    valid_object_id(body.doc_id)
    try:
        with AuditContext.with_user(str(current_user.id)):
            cluster = await ClusterService.add_member(
                cluster, body.doc_type, body.doc_id
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return cluster_out(cluster)


@router.delete("/clusters/{cluster_id}/members/{doc_type}/{doc_id}")
async def remove_cluster_member(
    cluster_id: str,
    doc_type: DocType,
    doc_id: str,
    current_user: User = Depends(get_current_user),
):
    """Remove a member; automatic rebuilds will not add it back."""
    cluster = await _get_or_404(cluster_id)
    valid_object_id(doc_id)
    with AuditContext.with_user(str(current_user.id)):
        cluster = await ClusterService.remove_member(cluster, doc_type, doc_id)
    return cluster_out(cluster)


@router.get("/clusters/{cluster_id}/suggestions")
async def cluster_suggestions(cluster_id: str, k: int = Query(10, ge=1, le=100)):
    """Non-member documents closest to the cluster centroid."""
    cluster = await _get_or_404(cluster_id)
    return {"suggestions": await ClusterService.suggestions(cluster, k=k)}


@router.post("/clusters/{cluster_id}/summarize")
async def summarize_cluster(
    cluster_id: str, current_user: User = Depends(get_current_user)
):
    """Regenerate the cluster's title (auto clusters only), summary and keywords."""
    cluster = await _get_or_404(cluster_id)
    try:
        with AuditContext.with_user(str(current_user.id)):
            cluster = await ClusterService.summarize(cluster)
    except Exception as e:
        logger.error(f"Summary failed for cluster {cluster_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Summary generation failed",
        )
    return cluster_out(cluster)


@router.get("/incidents/{report_id}/clusters")
async def incident_clusters(report_id: str):
    valid_object_id(report_id)
    clusters = await ClusterService.clusters_for("incident", report_id)
    return {"clusters": [cluster_out(c) for c in clusters]}


@router.get("/overviews/{overview_id}/clusters")
async def overview_clusters(overview_id: str):
    valid_object_id(overview_id)
    clusters = await ClusterService.clusters_for("overview", overview_id)
    return {"clusters": [cluster_out(c) for c in clusters]}
