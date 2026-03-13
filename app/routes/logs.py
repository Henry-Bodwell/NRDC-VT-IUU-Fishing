import logging

from beanie import PydanticObjectId
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pymongo import DESCENDING

from app.audit.models import AuditLog
from app.auth import get_current_admin_user
from app.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/{document_id}")
async def get_document_logs(
    document_id: str,
    limit: int = 25,
    skip: int = 0,
    current_user: User = Depends(get_current_admin_user),
):
    """Get all audit logs for a specific document by its ID.

    Requires admin authentication."""
    try:
        object_id = PydanticObjectId(document_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document_id format")

    document_logs = (
        await AuditLog.find(AuditLog.document_id == object_id)
        .sort([("timestamp", DESCENDING)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )

    total_count = await AuditLog.find(AuditLog.document_id == document_id).count()

    return {
        "logs": document_logs,
        "pagination": {
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + limit) < total_count,
        },
    }


@router.get("")
async def list_all_logs(
    limit: int = 25,
    skip: int = 0,
    current_user: User = Depends(get_current_admin_user),
):
    """
    Retrieves a list of all logs with pagination.

    Requires admin authentication.
    """
    document_logs = (
        await AuditLog.find({})
        .sort([("timestamp", DESCENDING)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )

    total_count = await AuditLog.find({}).count()

    return {
        "logs": document_logs,
        "pagination": {
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + limit) < total_count,
        },
    }
