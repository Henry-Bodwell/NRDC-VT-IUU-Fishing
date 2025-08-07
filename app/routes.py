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
from typing import List
from pydantic import BaseModel, ValidationError
from app.models.incidents import IncidentReponse, IncidentReport
from app.models.articles import Source
from app.incident_service import IncidentService
from pymongo.errors import DuplicateKeyError

router = APIRouter()
import logging

logger = logging.getLogger(__name__)


class URLRequest(BaseModel):
    url: str


@router.post("/incidents", response_model=IncidentReponse, status_code=201)
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
        existing_report = await _check_for_existing_url_report(url_payload.url)
        if existing_report:
            return {
                "status": "duplicate",
                "report": existing_report.model_dump(
                    exclude={"sources": {"__all__": {"incidents"}}}
                ),
                "message": "Source already exists for this URL.",
            }

        # Create new report using the service
        saved_report = await IncidentService.create_report_from_url(url=url_payload.url)

        if not saved_report:
            raise HTTPException(
                status_code=422,
                detail="Failed to process the URL or save the report. The source may be invalid or no relevant information was found.",
            )

        return {
            "status": "success",
            "report": saved_report.model_dump(
                exclude={"sources": {"__all__": {"incidents"}}}
            ),
            "message": "Incident report created successfully.",
        }

    except ValidationError as e:
        logger.error(f"Validation error in URL request: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors()
        )
    except DuplicateKeyError as e:
        logger.error(f"Duplicate key error: {e}")
        # Try to find and return existing document
        if "url_payload" in locals():
            existing = await _check_for_existing_url_report(url_payload.url)
            if existing:
                return {
                    "status": "duplicate",
                    "report": existing_report.model_dump(
                        exclude={"sources": {"__all__": {"incidents"}}}
                    ),
                    "message": "Incident report already exists for this URL.",
                }

        raise HTTPException(
            status_code=409,
            detail="Duplicate key error occurred but could not find existing document.",
        )
    except HTTPException:
        # Re-raise HTTP exceptions from the service
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
            "report": result.model_dump() if hasattr(result, "model_dump") else result,
            "message": "File processed successfully.",
        }

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in file request: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the file.",
        )


async def _check_for_existing_url_report(url: str) -> Source | None:
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
async def get_incident_reports(skip: int = 0, limit: int = 10):
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
    throw_exception(report)
    return report


def throw_exception(response: IncidentReport):
    """
    Helper function to throw an exception if the response is not valid.
    """
    if not response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident report not found.",
        )

    if not isinstance(response, IncidentReport):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve incident report.",
        )


@router.get("/test")
async def test_route():
    return {"message": "Router is working!"}
