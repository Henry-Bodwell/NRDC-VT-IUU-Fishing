import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Query,
    HTTPException,
    status,
)
from pymongo import DESCENDING

from app.models.task import TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(
    user_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = 25,
    skip: int = 0,
):
    """
    List all tasks with optional filtering by user_id and status.
    """
    query_filters = {}

    if user_id:
        query_filters["user_id"] = user_id

    if status_filter:
        query_filters["status"] = status_filter

    tasks = (
        await TaskStatus.find(query_filters)
        .sort([("created_at", DESCENDING)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )

    total_count = await TaskStatus.find(query_filters).count()

    return {
        "tasks": [
            {
                "task_id": task.task_id,
                "status": task.status,
                "task_type": task.task_type,
                "progress": task.progress,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
            for task in tasks
        ],
        "pagination": {
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + limit) < total_count,
        },
    }


@router.get("/{task_id}")
async def get_task_status(task_id: str):
    """
    Get the status of a background task by its ID.
    """
    task = await TaskStatus.find_one(TaskStatus.task_id == task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    return {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }
