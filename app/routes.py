from fastapi import (
    APIRouter,
    Body,
    Depends,
    Request,
    Response,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from typing import List, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError
from app.models.incidents import IncidentReport
from app.models.articles import Source
from app.incident_service import IncidentService
from pymongo.errors import DuplicateKeyError
from app.source_service import SourceService


router = APIRouter()
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class URLRequest(BaseModel):
    url: str


# Incident Routes
@router.post(
    "/incidents", response_model=IncidentReport, status_code=status.HTTP_201_CREATED
)
async def create_incident_report(request: Request):
    """
    Submits a URL or file for analysis and saves the resulting incident report to database.
    """
    content_type = request.headers.get("content-type")

    # Extract context data from request (adjust based on your auth/context setup)
    context_data = {
        "acting_user_id": request.headers.get("x-user-id"),  # Adjust based on your auth
        "source": "api",
        "request_id": request.headers.get("x-request-id"),
    }

    if content_type == "application/json":
        return await _handle_url_request(request, context_data)
    elif content_type and content_type.startswith("multipart/form-data"):
        return await _handle_file_request(request, context_data)
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported Content-Type: {content_type}. Must be 'application/json' or 'multipart/form-data'",
        )


async def _handle_url_request(request: Request, context_data: dict) -> dict:
    """Handle JSON URL request"""
    try:
        json_payload = await request.json()
        url_payload = URLRequest(**json_payload)

        # Check for existing report first (optional - depends on your business logic)
        existing_source = await _check_for_existing_url(url_payload.url)
        if existing_source:
            logger.error(f"Duplicate key error: {e}")
            raise HTTPException(
                status_code=409,
                detail=f"Source already exists for {url_payload.url}",
            )

        # Create new report using the service
        saved_report = await IncidentService.create_report_from_url(url=url_payload.url)

        valid_response(saved_report, IncidentReport)

        logger.info(f"Incident report created: {saved_report.id}")
        return saved_report.model_dump(
            exclude={"sources", "primary_source"},  # Exclude problematic fields
            mode="json",  # Ensures proper serialization
        )

    except ValidationError as e:
        logger.error(f"Validation error in URL request: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors()
        )
    except DuplicateKeyError as e:
        logger.error(f"Unexpected duplicate key error (race condition?): {e}")
        try:
            existing_source = await _check_for_existing_url(url_payload.url)
            if existing_source:
                return {
                    "status": "duplicate",
                    "message": f"Source already exists for {url_payload.url} (created by concurrent request)",
                }
        except Exception as lookup_error:
            logger.error(
                f"Failed to lookup existing document after duplicate key error: {lookup_error}"
            )

        raise HTTPException(
            status_code=409,
            detail="Duplicate key error occurred due to concurrent processing.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in URL request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the request.",
        )


async def _handle_file_request(request: Request, context_data: dict) -> dict:
    """Handle multipart file request"""
    try:
        form = await request.form()
        file = form.get("file")

        if not file or not isinstance(file, UploadFile):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A 'file' part is required for multipart/form-data.",
            )

        # Use the service to handle file processing
        result = await IncidentService.create_report_from_file(
            file=file, context_data=context_data
        )

        if isinstance(result, dict) and result.get("status") == "error":
            # Service returned error (like not implemented)
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=result.get("detail", "File processing not implemented yet."),
            )

        return {
            "status": "success",
            "report": result,
            "message": "File processed successfully.",
        }

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


@router.get("/incidents", response_model=List[IncidentReport])
async def list_incident_reports(skip: int = 0, limit: int = 25):
    """
    Retrieves a list of incident reports with pagination.
    """
    reports = await IncidentReport.find_all().skip(skip).limit(limit).to_list()
    return reports


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
async def update_incident_report(report_id: str, update_data: IncidentReport):
    """Updates an existing incident report by its ID."""
    try:
        updated_report = await IncidentService.update_report(
            report_id=report_id, update_data=update_data.model_dump()
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
@router.get("/sources", response_model=List[Source])
async def list_sources(skip: int = 0, limit: int = 25):
    sources = await Source.find_all().skip(skip).limit(limit).to_list()
    return sources


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
async def update_source(source_id: str, update_data: Source):
    updated_source = await SourceService.update_source(
        source_id=source_id, update_data=update_data
    )


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


@router.get("/test")
async def test_route():
    return {"message": "Router is working!"}
