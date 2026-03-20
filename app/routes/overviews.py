import logging

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Response,
    HTTPException,
    status,
)
from pymongo import ASCENDING, DESCENDING
from typing import Annotated

from app.auth import get_current_user, get_current_admin_user
from app.interfaces import OverviewFilters
from app.models.incidents import IndustryOverview
from app.models.users import User
from app.service.overview_service import OverviewService
from app.routes.helpers import valid_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/overviews", tags=["overviews"])


@router.delete(
    "/{overview_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_overview(
    overview_id: str,
    current_user: User = Depends(get_current_admin_user),
):
    try:
        was_deleted = await OverviewService.delete_overview(overview_id)
        if was_deleted:
            return
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Industry overview not found",
            )
    except Exception as e:
        logger.error(f"Error deleting industry overview {overview_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete industry overview.",
        )


@router.put("/{overview_id}", response_model=IndustryOverview)
async def update_overview(
    overview_id: str,
    update_data: dict,
    current_user: User = Depends(get_current_user),
):
    """Updates an existing industry overview by its ID."""
    try:
        updated_overview = await OverviewService.update_overview(
            overview_id=overview_id, update_data=update_data
        )
        valid_response(updated_overview, IndustryOverview)
        return updated_overview
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "update_failed",
                "message": "Failed to update industry overview",
                "details": str(e),
            },
        )


@router.get("/{overview_id}", response_model=IndustryOverview)
async def get_overview(overview_id: str):
    overview = await IndustryOverview.get(overview_id)
    valid_response(overview, IndustryOverview)
    return overview


@router.get("")
async def list_overviews(filter_query: Annotated[OverviewFilters, Query()]):
    """
    Retrieves a list of industry overviews with pagination and filtering.
    """
    query_filters = {}

    if filter_query.input_category != "all":
        query_filters["source.input_category"] = filter_query.input_category

    if filter_query.status != "all":
        query_filters["status"] = filter_query.status

    if filter_query.verified != "all":
        query_filters["verified"] = filter_query.verified == "true"

    # Date range filters
    if filter_query.created_after:
        query_filters["created_at"] = query_filters.get("created_at", {})
        query_filters["created_at"]["$gte"] = filter_query.created_after
    if filter_query.created_before:
        query_filters["created_at"] = query_filters.get("created_at", {})
        query_filters["created_at"]["$lte"] = filter_query.created_before
    if filter_query.modified_after:
        query_filters["updated_at"] = query_filters.get("updated_at", {})
        query_filters["updated_at"]["$gte"] = filter_query.modified_after
    if filter_query.modified_before:
        query_filters["updated_at"] = query_filters.get("updated_at", {})
        query_filters["updated_at"]["$lte"] = filter_query.modified_before

    # User filters
    if filter_query.created_by:
        query_filters["created_by"] = filter_query.created_by
    if filter_query.modified_by:
        query_filters["updated_by"] = filter_query.modified_by

    if filter_query.search:
        query_filters["$text"] = {"$search": filter_query.search}

    sort_direction = ASCENDING if filter_query.sort_order == "asc" else DESCENDING
    sort_field = filter_query.sort_by

    overviews = (
        await IndustryOverview.find(query_filters, fetch_links=False)
        .sort([(sort_field, sort_direction)])
        .skip(filter_query.skip)
        .limit(filter_query.limit)
        .to_list()
    )

    total_count = await IndustryOverview.find(query_filters).count()

    return {
        "overviews": overviews,
        "pagination": {
            "total": total_count,
            "skip": filter_query.skip,
            "limit": filter_query.limit,
            "has_more": (filter_query.skip + filter_query.limit) < total_count,
        },
    }
