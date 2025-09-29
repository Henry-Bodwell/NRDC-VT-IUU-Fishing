import json
from beanie import PydanticObjectId
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Query,
    Request,
    Response,
    HTTPException,
    UploadFile as FastAPIUploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pymongo import DESCENDING
from starlette.datastructures import UploadFile
from fastapi.encoders import jsonable_encoder
from typing import Annotated, List, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError, model_validator
from app.audit.context import AuditContext
from app.audit.models import AuditLog
from app.models.incidents import IncidentReport, IndustryOverview
from app.models.articles import Source
from app.service.incident_service import IncidentService
from pymongo.errors import DuplicateKeyError
from app.service.overview_service import OverviewService
from app.service.source_service import SourceService
from app.dspy_files.news_analysis import PipelineOutput
from app.interfaces import GenRequest, IncidentFilters, SourceFilters


router = APIRouter()
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# Incident Routes
@router.post(
    "/incidents", response_model=PipelineOutput, status_code=status.HTTP_201_CREATED
)
async def create_incident_report(request: Request):
    """
    Submits a URL or file for analysis and saves the resulting incident report to database.
    """
    content_type = request.headers.get("content-type")

    context_data = {
        "source": "api",
    }

    try:
        if content_type == "application/json":
            return await _handle_json_request(request, context_data)
        elif content_type and content_type.startswith("multipart/form-data"):
            return await _handle_file_request(request, context_data)
        else:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported Content-Type: {content_type}. Must be 'application/json' or 'multipart/form-data'",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inserting incident report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to insert incident report. {e}",
        )


def _request_response(pipeline_output: PipelineOutput):

    if pipeline_output.is_success:
        if pipeline_output.has_overview:
            overview = pipeline_output.industry_overview
            if isinstance(overview, IndustryOverview):
                valid_response(overview, IndustryOverview)
                logger.info(f"Industry Overview created: {overview.id}")

        if pipeline_output.has_incident:
            for incident in pipeline_output.incidents:
                report = incident
                if isinstance(report, IncidentReport):
                    valid_response(report, IncidentReport)
                    logger.info(f"Incident report created: {report.id}")

    return pipeline_output.model_dump(
        exclude={
            "source": {"incidents", "overview"},
            "incidents": {"__all__": {"sources", "primary_source"}},
            "industry_overview": {"source"},
        }
    )


async def _handle_json_request(request, context_data):
    try:
        json_payload = await request.json()
        payload = GenRequest(**json_payload)
        if payload.user_id:
            user = payload.user_id
        with AuditContext.with_user(user):
            if payload.url:
                existing_source = await _check_for_existing_url(payload.url)
                if existing_source:
                    logger.error(f"Source already exists for {payload.url}")
                    raise HTTPException(
                        status_code=409,
                        detail=f"Source already exists for {payload.url}",
                    )
                output = await IncidentService.create_report_from_url(payload.url)
            elif payload.text:
                output = await IncidentService.create_report_from_text(payload.text)
            else:
                raise ValueError("Payload must include either 'text' or 'url'")
            return _request_response(output)
    except ValidationError as e:
        logger.error(f"Validation error in request: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors()
        )
    except json.JSONDecodeError as e:
        return JSONResponse({"error": "Invalid JSON format"}, status_code=400)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the request.",
        )


async def _handle_file_request(request: Request, context_data: dict) -> dict:
    """Handle multipart file request"""
    try:
        form = await request.form()
        logger.info(f"Form recevied with keys: {list(form.keys())}")
        pdf_file = None
        for key, value in form.items():
            logger.info(f"Key: {key}, Value type: {type(value)}, Value: {value}")
            if isinstance(value, (UploadFile, FastAPIUploadFile)):
                if not value.filename:
                    continue

                allowed_types = [
                    "application/pdf",
                    "application/x-pdf",
                    "application/acrobat",
                ]
                if value.content_type not in allowed_types:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File must be a PDF. Received: {value.content_type}",
                    )
                pdf_file = value
                break

        if not pdf_file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No PDF file found in request",
            )

        pdf_bytes = await pdf_file.read()

        output = await IncidentService.create_report_from_pdf(
            pdf_bytes, pdf_file.filename
        )

        return _request_response(output)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in file request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the file.",
        )


async def _check_for_existing_url(url: str) -> Source | None:
    """
    Check if a report already exists for the given URL.
    Adjust this query based on your actual data model structure.
    """
    try:
        existing = await Source.find_one(Source.url == url)
        return existing
    except Exception as e:
        logger.warning(f"Error checking for existing report: {e}")
        return None


@router.get("/incidents")
async def list_incident_reports(filter_query: Annotated[IncidentFilters, Query()]):
    """
    Retrieves a l ncident reports with pagination and filtering.
    """
    query_filters = {}

    if filter_query.source_type != "all":
        query_filters["primary_source.category"] = filter_query.source_type

    if filter_query.verified != "all":
        query_filters["verified"] = filter_query.verified == "true"

    if filter_query.IUU_type != "all":
        query_filters["incident_classification.iuuClassifications"] = {
            "$elemMatch": {"IUUType": filter_query.IUU_type}
        }
    if filter_query.status != "all":
        query_filters["status"] = filter_query.status
    sort_direction = DESCENDING
    sort_field = filter_query.sort_by

    logger.info(f"Query Filters: {query_filters}")
    reports = (
        await IncidentReport.find(query_filters, fetch_links=True, nesting_depth=1)
        .sort([(sort_field, sort_direction)])
        .skip(filter_query.skip)
        .limit(filter_query.limit)
        .to_list()
    )

    total_count = await IncidentReport.find(query_filters).count()

    return {
        "reports": reports,
        "pagination": {
            "total": total_count,
            "skip": filter_query.skip,
            "limit": filter_query.limit,
            "has_more": (filter_query.skip + filter_query.limit) < total_count,
        },
    }


@router.get("/incidents/{report_id}", response_model=IncidentReport)
async def get_incident_report(report_id: str):
    """
    Retrieves a specific incident report by its ID.
    """
    report = await IncidentReport.get(report_id)
    valid_response(report, IncidentReport)
    return report


@router.delete(
    "/incidents/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_incident(report_id: str):
    """
    Deletes an incident report by its ID.
    """

    try:
        was_deleted = await IncidentService.delete_report(report_id=report_id)
        if was_deleted:
            return
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident report not found",
            )
    except Exception as e:
        logger.error(f"Error deleting incident report {report_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete incident report.",
        )


@router.put("/incidents/{report_id}", response_model=IncidentReport)
async def update_incident_report(report_id: str, update_data: dict):
    """Updates an existing incident report by its ID."""
    try:
        updated_report = await IncidentService.update_report(
            report_id=report_id, update_data=update_data
        )
        valid_response(updated_report, IncidentReport)
        return updated_report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "update_failed",
                "message": "Failed to update incident report",
                "details": str(e),
            },
        )


# Source routes
@router.get("/sources")
async def list_sources(filter_query: Annotated[SourceFilters, Query()]):
    """
    Retrieves a list of sources with pagination and filtering.
    """
    query_filters = {}

    if filter_query.source_type != "all":
        query_filters["category"] = filter_query.source_type

    if filter_query.verified != "all":
        query_filters["verified"] = filter_query.verified == "true"

    if filter_query.article_scope != "all":
        query_filters["article_scope"] = filter_query.article_scope
    sort_direction = DESCENDING
    sort_field = filter_query.sort_by

    logger.info(f"Query Filters: {query_filters}")
    sources = (
        await Source.find(query_filters, fetch_links=True, nesting_depth=1)
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


@router.get("/sources/{source_id}", response_model=Source)
async def get_source(source_id: str):
    source = await Source.get(source_id)
    valid_response(source, Source)
    return source


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_source(source_id: str):
    try:
        was_deleted = await SourceService.delete(source_id)
        if was_deleted:
            return
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source not found",
            )
    except Exception as e:
        logger.error(f"Error deleting source {source_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete source.",
        )


@router.put("/sources/{source_id}", response_model=Source)
async def update_source(source_id: str, update_data: dict):
    """Updates an existing incident report by its ID."""
    try:
        updated_source = await SourceService.update_source(
            source_id=source_id, update_data=update_data
        )
        valid_response(updated_source, Source)
        return updated_source
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "update_failed",
                "message": "Failed to update source",
                "details": str(e),
            },
        )


# Overview routes
@router.delete(
    "/overviews/{overview_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_overview(overview_id: str):
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


@router.put("/overviews/{overview_id}", response_model=IndustryOverview)
async def update_overview(overview_id: str, update_data: dict):
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


@router.get("/overviews/{overview_id}", response_model=IndustryOverview)
async def get_overview(overview_id: str):
    overview = await IndustryOverview.get(overview_id)
    valid_response(overview, IndustryOverview)
    return overview


@router.get("/overviews")
async def list_overviews(limit: int = 25, skip: int = 0):
    """
    Retrieves a list of industry overviews with pagination.
    """
    overviews = (
        await IndustryOverview.find({}, fetch_links=True, nesting_depth=1)
        .sort([("created_at", DESCENDING)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )

    total_count = await IndustryOverview.find({}).count()

    return {
        "overviews": overviews,
        "pagination": {
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + limit) < total_count,
        },
    }


def valid_response(response: Optional[T], pydanticModel: Type[T]):
    """
    Helper function to throw an exception if the response is not valid.
    """
    if not response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "not_found",
                "message": f"{pydanticModel.__name__} not found",
            },
        )

    if not isinstance(response, pydanticModel):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "invalid_response",
                "message": f"Expected {pydanticModel.__name__}, got {type(response).__name__}",
            },
        )


# Audit Logs
@router.get("/logs/{document_id}")
async def get_document_logs(document_id: str, limit: int = 25, skip: int = 0):
    """Get all audit logs for a specific document by its ID."""
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


@router.get("/logs")
async def list_all_logs(limit: int = 25, skip: int = 0):
    """
    Retrieves a list of all logs with pagination.
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


@router.get("/ping")
async def ping():
    return {"message": "Pong"}
