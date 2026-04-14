import json
import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    Response,
    HTTPException,
    UploadFile as FastAPIUploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pymongo import ASCENDING, DESCENDING
from starlette.datastructures import UploadFile
from typing import Annotated, List
from pydantic import ValidationError

from app.auth import get_current_user, get_current_admin_user
from app.interfaces import (
    AddSourceRequest,
    GenRequest,
    IncidentFilters,
)
from app.literals import IUUType
from app.models.incidents import IncidentReport
from app.models.sources import Source
from app.models.task import TaskStatus
from app.models.users import User
from app.service.incident_service import IncidentService
from app.routes.helpers import valid_object_id, valid_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_incident_report(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """
    Submits a URL or file for analysis and saves the resulting incident report to database.
    Returns a task_id immediately for status polling.

    Rate limit: 30/hour for regular IPs (can be whitelisted for bulk processing)
    Authentication: Required (Bearer token)
    """
    content_type = request.headers.get("content-type")

    try:
        if content_type == "application/json":
            return await _handle_json_request(request, background_tasks, current_user)
        elif content_type and content_type.startswith("multipart/form-data"):
            return await _handle_file_request(request, background_tasks, current_user)
        else:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported Content-Type: {content_type}. Must be 'application/json' or 'multipart/form-data'",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task. {e}",
        )


async def _handle_json_request(
    request, background_tasks: BackgroundTasks, current_user: User
):
    try:
        json_payload = await request.json()
        payload = GenRequest(**json_payload)
        user_id = str(current_user.id)

        # Create task
        task = TaskStatus(
            task_type="incident_analysis",
            user_id=user_id,
            status="pending",
        )

        if payload.text:
            task.input_params = {
                "input_type": "text",
                "text": (
                    payload.text[:100] + "..."
                    if len(payload.text) > 100
                    else payload.text
                ),
                "url": payload.url if payload.url else None,
            }
            if payload.url:
                existing_source = await _check_for_existing_url(payload.url)
                if existing_source:
                    logger.error(f"Source already exists for {payload.url}")
                    raise HTTPException(
                        status_code=409,
                        detail=f"Source already exists for {payload.url}",
                    )

            existing_text = await _check_for_existing_text(payload.text)
            if existing_text:
                logger.error(f"Source already exists for {payload.text[:50]}...")
                raise HTTPException(
                    status_code=409,
                    detail=f"Source already exists for {payload.text[:50]}...",
                )

            await task.insert()

            # Schedule background task
            background_tasks.add_task(
                IncidentService.run_analysis_with_task_tracking,
                task_id=task.task_id,
                input_type="text",
                text=payload.text,
                url=payload.url if payload.url else None,
                author=payload.author if payload.author else None,
                title=payload.title if payload.title else None,
                publisher=payload.publisher if payload.publisher else None,
                date=payload.publication_date if payload.publication_date else None,
                source_type=payload.source_type,
                status=payload.status,
                input_name=payload.input_name if payload.input_name else None,
            )

        elif payload.url:
            # Check for existing URL
            existing_source = await _check_for_existing_url(payload.url)
            if existing_source:
                logger.error(f"Source already exists for {payload.url}")
                raise HTTPException(
                    status_code=409,
                    detail=f"Source already exists for {payload.url}",
                )

            task.input_params = {"input_type": "url", "url": payload.url}
            await task.insert()

            # Schedule background task
            background_tasks.add_task(
                IncidentService.run_analysis_with_task_tracking,
                task_id=task.task_id,
                input_type="url",
                url=payload.url,
                source_type=payload.source_type,
                input_name=payload.input_name if payload.input_name else None,
            )
        else:
            raise ValueError("Payload must include either 'text' or 'url'")

        return {"task_id": task.task_id, "status": "pending"}

    except ValidationError as e:
        logger.error(f"Validation error in request: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors()
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON format"}, status_code=400)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the request.",
        )


async def _handle_file_request(
    request: Request, background_tasks: BackgroundTasks, current_user: User
) -> dict:
    """Handle multipart file request"""
    try:
        form = await request.form()
        logger.info(f"Form received with keys: {list(form.keys())}")
        pdf_file = None
        user_id = str(current_user.id)

        # Extract metadata from form fields
        metadata = {}
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
            elif isinstance(value, str):
                # Collect string metadata fields
                if key in [
                    "title",
                    "author",
                    "publisher",
                    "url",
                    "source_type",
                    "status",
                    "input_name",
                ]:
                    metadata[key] = value
                elif key == "publication_date":
                    from datetime import datetime

                    try:
                        metadata[key] = datetime.fromisoformat(
                            value.replace("Z", "+00:00")
                        )
                    except Exception as e:
                        logger.warning(
                            f"Could not parse publication_date: {value}, error: {e}"
                        )

        logger.info(f"Extracted metadata: {metadata}")

        if not pdf_file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No PDF file found in request",
            )

        pdf_bytes = await pdf_file.read()

        # Validate PDF file size (max 50MB)
        MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB in bytes
        if len(pdf_bytes) > MAX_PDF_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"PDF file too large. Maximum size is 50MB, received {len(pdf_bytes) / (1024 * 1024):.2f}MB",
            )

        # Validate minimum file size to ensure it's not empty
        if len(pdf_bytes) < 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF file appears to be empty or corrupted",
            )

        # Check for duplicate PDF by extracting text and computing hash
        from app.dspy_files.content_extraction import ContentExtractor
        import hashlib

        try:
            temp_source = ContentExtractor.from_pdf(pdf_bytes)
            if temp_source.article_text:
                text_hash = hashlib.sha256(
                    temp_source.article_text.encode()
                ).hexdigest()
                existing_source = await Source.find_one(
                    Source.article_hash == text_hash
                )
                if existing_source:
                    logger.warning(
                        f"PDF with same content already exists: {pdf_file.filename} (hash: {text_hash})"
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=f"A source with identical content already exists (ID: {existing_source.id})",
                    )
        except HTTPException:
            raise
        except Exception as e:
            # If text extraction fails here, let it continue - the background task will handle the error
            logger.warning(
                f"Could not check for duplicate during upload (will check later): {e}"
            )

        # Create task with metadata
        input_params = {"input_type": "pdf", "filename": pdf_file.filename}
        input_params.update(metadata)

        task = TaskStatus(
            task_type="incident_analysis",
            user_id=user_id,
            status="pending",
            input_params=input_params,
        )
        await task.insert()

        # Schedule background task with metadata
        background_tasks.add_task(
            IncidentService.run_analysis_with_task_tracking,
            task_id=task.task_id,
            input_type="pdf",
            pdf_bytes=pdf_bytes,
            filename=pdf_file.filename,
            **metadata,
        )

        return {"task_id": task.task_id, "status": "pending"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in file request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the file.",
        )


async def _check_for_existing_text(text: str) -> Source | None:
    """
    Check if a source already exists for the given text by comparing article_hash.
    """
    try:
        import hashlib

        article_hash = hashlib.sha256(text.encode()).hexdigest()
        existing = await Source.find_one(Source.article_hash == article_hash)
        return existing
    except Exception as e:
        logger.warning(f"Error checking for existing text: {e}")
        return None


async def _check_for_existing_url(url: str) -> Source | None:
    """
    Check if a report already exists for the given URL.
    """
    try:
        existing = await Source.find_one(Source.url == url)
        return existing
    except Exception as e:
        logger.warning(f"Error checking for existing report: {e}")
        return None


@router.get("")
async def list_incident_reports(filter_query: Annotated[IncidentFilters, Query()]):
    """
    Retrieves a l incident reports with pagination and filtering.
    """
    query_filters = {}

    # if filter_query.input_category != "all":
    #     query_filters["primary_source.input_category"] = filter_query.input_category

    if filter_query.verified != "all":
        query_filters["verified"] = filter_query.verified == "true"

    elem_match: dict = {}
    if filter_query.IUU_type != "all":
        elem_match["IUUType"] = filter_query.IUU_type
    if filter_query.IUU_subtype:
        elem_match["IUUSubType"] = {"$in": list(filter_query.IUU_subtype)}
    if elem_match:
        query_filters["incident_classification.iuuClassifications"] = {
            "$elemMatch": elem_match
        }
    if filter_query.status != "all":
        query_filters["status"] = filter_query.status

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

    # Event date filters
    if filter_query.event_date_after:
        query_filters["extracted_information.eventData.eventDate"] = query_filters.get(
            "extracted_information.eventData.eventDate", {}
        )
        query_filters["extracted_information.eventData.eventDate"][
            "$gte"
        ] = filter_query.event_date_after
    if filter_query.event_date_before:
        query_filters["extracted_information.eventData.eventDate"] = query_filters.get(
            "extracted_information.eventData.eventDate", {}
        )
        query_filters["extracted_information.eventData.eventDate"][
            "$lte"
        ] = filter_query.event_date_before

    # Location filters
    if filter_query.event_location:
        query_filters["extracted_information.eventData.eventLocation"] = {
            "$regex": filter_query.event_location,
            "$options": "i",
        }
    if filter_query.event_country:
        query_filters["extracted_information.eventData.eventCountry"] = {
            "$regex": filter_query.event_country,
            "$options": "i",
        }
    if filter_query.event_location_category != "all":
        query_filters["extracted_information.eventData.eventLocationCategory"] = (
            filter_query.event_location_category
        )

    # Vessel filters
    if filter_query.vessel_name:
        query_filters["extracted_information.vesselInformation.vesselName"] = {
            "$regex": filter_query.vessel_name,
            "$options": "i",
        }
    if filter_query.vessel_flag:
        query_filters["extracted_information.vesselInformation.flagState"] = {
            "$regex": filter_query.vessel_flag,
            "$options": "i",
        }

    # Species filter
    if filter_query.species_common_name:
        query_filters["extracted_information.speciesInvolved"] = {
            "$elemMatch": {
                "speciesCommonName": {
                    "$regex": filter_query.species_common_name,
                    "$options": "i",
                }
            }
        }

    # Enforcement category filter
    if filter_query.enforcement_category:
        query_filters["extracted_information.eventData.enforcementCategory"] = {
            "$regex": filter_query.enforcement_category,
            "$options": "i",
        }

    if filter_query.search:
        query_filters["$text"] = {"$search": filter_query.search}

    sort_direction = ASCENDING if filter_query.sort_order == "asc" else DESCENDING
    sort_field = filter_query.sort_by

    logger.info(f"Query Filters: {query_filters}")
    reports = (
        await IncidentReport.find(query_filters, fetch_links=False)
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


@router.get("/types")
async def get_incident_types(types: Annotated[List[IUUType] | None, Query()] = None):
    """
    Retrieves the list of IUU types and subtypes for filtering and form options.
    """
    return {
        "IUU_types_and_subtypes": IncidentService.get_IUU_types(types),
    }


@router.get("/{report_id}", response_model=IncidentReport)
async def get_incident_report(report_id: str):
    """
    Retrieves a specific incident report by its ID.
    """
    valid_object_id(report_id)
    report = await IncidentReport.get(report_id, fetch_links=False)
    valid_response(report, IncidentReport)
    return report


@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_incident(
    report_id: str,
    current_user: User = Depends(get_current_admin_user),
):
    """
    Deletes an incident report by its ID.
    """
    valid_object_id(report_id)
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


@router.post("/{report_id}/sources", response_model=IncidentReport)
async def add_source_to_incident(
    report_id: str,
    body: AddSourceRequest,
    current_user: User = Depends(get_current_admin_user),
):
    """Adds a source to an incident report by ID."""
    valid_object_id(report_id)
    return await IncidentService.add_source_to_report(
        report_id=report_id,
        source_id=body.source_id,
        is_primary=body.is_primary,
    )


@router.delete(
    "/{report_id}/sources/{source_id}",
    response_model=IncidentReport,
)
async def remove_source_from_incident(
    report_id: str,
    source_id: str,
    current_user: User = Depends(get_current_admin_user),
):
    """Removes a source from an incident report."""
    valid_object_id(report_id)
    valid_object_id(source_id)
    return await IncidentService.remove_source_from_report(
        report_id=report_id,
        source_id=source_id,
    )


@router.put("/{report_id}", response_model=IncidentReport)
async def update_incident_report(
    report_id: str,
    update_data: dict,
    current_user: User = Depends(get_current_user),
):
    """Updates an existing incident report by its ID."""
    valid_object_id(report_id)

    validation_errors = IncidentReport.validate_update_data(update_data)
    if validation_errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_update_data", "errors": validation_errors},
        )
    try:
        updated_report = await IncidentService.update_report(
            report_id=report_id, update_data=update_data
        )
        valid_response(updated_report, IncidentReport)
        return updated_report
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating incident report {report_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "update_failed",
                "message": "Failed to update incident report",
                "details": str(e),
            },
        )
