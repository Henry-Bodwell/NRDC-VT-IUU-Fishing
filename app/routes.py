from fastapi import (
    APIRouter,
    Body,
    Depends,
    Request,
    Response,
    HTTPException,
    UploadFile as FastAPIUploadFile,
    status,
)
from starlette.datastructures import UploadFile
from fastapi.encoders import jsonable_encoder
from typing import List, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError, model_validator
from app.models.incidents import IncidentReport, IndustryOverview
from app.models.articles import Source
from app.incident_service import IncidentService
from pymongo.errors import DuplicateKeyError
from app.source_service import SourceService
from app.dspy_files.news_analysis import PipelineOutput


router = APIRouter()
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GenRequest(BaseModel):
    url: str | None = None
    text: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def check_at_least_one_field(self):
        if not any([self.url, self.text]):
            raise ValueError("Either url or text must be provided")
        return self


# Incident Routes
@router.post(
    "/incidents", response_model=PipelineOutput, status_code=status.HTTP_201_CREATED
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
            "source": "incidents",
            "incidents": {"__all__": {"sources", "primary_source"}},
            "industry_overview": {"source"},
        }
    )


async def _handle_json_request(request, context_data):
    try:
        json_payload = await request.json()
        payload = GenRequest(**json_payload)

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


@router.get("/ping")
async def ping():
    return {"message": "Pong"}
