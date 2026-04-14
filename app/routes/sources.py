import logging

from fastapi import (
    APIRouter,
    Depends,
    Query,
    HTTPException,
    status,
)
from pymongo import ASCENDING, DESCENDING
from typing import Annotated

from app.auth import get_current_user, get_current_admin_user
from app.interfaces import SourceFilters
from app.models.sources import Source
from app.models.users import User
from app.service.source_service import SourceService
from app.routes.helpers import valid_object_id, valid_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("")
async def list_sources(filter_query: Annotated[SourceFilters, Query()]):
    """
    Retrieves a list of sources with pagination and filtering.
    """
    query_filters = {}

    if filter_query.input_category != "all":
        query_filters["input_category"] = filter_query.input_category

    if filter_query.source_type != "all":
        query_filters["source_type"] = filter_query.source_type

    if filter_query.status != "all":
        query_filters["status"] = filter_query.status

    if filter_query.verified != "all":
        query_filters["verified"] = filter_query.verified == "true"

    if filter_query.article_scope != "all":
        query_filters["article_scope.articleType"] = filter_query.article_scope

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

    # Publication date filters
    if filter_query.publication_date_after:
        query_filters["publication_date"] = query_filters.get("publication_date", {})
        query_filters["publication_date"]["$gte"] = filter_query.publication_date_after
    if filter_query.publication_date_before:
        query_filters["publication_date"] = query_filters.get("publication_date", {})
        query_filters["publication_date"]["$lte"] = filter_query.publication_date_before

    if filter_query.search:
        query_filters["$text"] = {"$search": filter_query.search}

    sort_direction = ASCENDING if filter_query.sort_order == "asc" else DESCENDING
    sort_field = filter_query.sort_by

    logger.info(f"Query Filters: {query_filters}")
    sources = (
        await Source.find(query_filters, fetch_links=False)
        .sort([(sort_field, sort_direction)])
        .skip(filter_query.skip)
        .limit(filter_query.limit)
        .to_list()
    )

    total_count = await Source.find(query_filters).count()

    return {
        "sources": sources,
        "pagination": {
            "total": total_count,
            "skip": filter_query.skip,
            "limit": filter_query.limit,
            "has_more": (filter_query.skip + filter_query.limit) < total_count,
        },
    }


@router.get("/{source_id}", response_model=Source)
async def get_source(source_id: str):
    valid_object_id(source_id)
    source = await Source.get(source_id)
    valid_response(source, Source)
    return source


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_source(
    source_id: str,
    current_user: User = Depends(get_current_admin_user),
):
    valid_object_id(source_id)

    try:
        was_deleted = await SourceService.delete_source(source_id)
        if was_deleted:
            return
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source not found",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting source {source_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete source.",
        )


@router.put("/{source_id}", response_model=Source)
async def update_source(
    source_id: str,
    update_data: dict,
    current_user: User = Depends(get_current_user),
):
    """Updates an existing source by its ID."""
    valid_object_id(source_id)
    validation_errors = Source.validate_update_data(update_data)
    if validation_errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_update_data", "errors": validation_errors},
        )
    try:
        updated_source = await SourceService.update_source(
            source_id=source_id, update_data=update_data
        )
        valid_response(updated_source, Source)
        return updated_source
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating source {source_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "update_failed",
                "message": "Failed to update source",
                "details": str(e),
            },
        )
