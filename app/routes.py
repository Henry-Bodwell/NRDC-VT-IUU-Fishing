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
from app.models.incidents import IncidentReport
from app.incident_service import IncidentService
from pymongo.errors import DuplicateKeyError
from beanie.exceptions import DuplicateKeyError as BeanieDuplicateKeyError

router = APIRouter()


class URLRequest(BaseModel):
    url: str


@router.post("/incidents", response_model=IncidentReport, status_code=201)
async def create_incident_report(request: Request):
    """
    Submits a URL for analysis and saves the resulting incident report to database.
    """
    content_type = request.headers.get("content-type")

    if content_type == "application/json":
        url_payload = None  # Initialize to avoid UnboundLocalError
        try:
            json_payload = await request.json()
            url_payload = URLRequest(**json_payload)
            saved_report = await IncidentService.create_report_from_url(url_payload)

            if not saved_report:
                raise HTTPException(
                    status_code=422,
                    detail="Failed to process the URL or save the report. The source may be invalid or no relevant information was found.",
                )

            return {"status": "success", "report": saved_report.model_dump()}

        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors()
            )
        except (DuplicateKeyError, BeanieDuplicateKeyError) as e:
            if url_payload:
                exist = await IncidentReport.find_one(
                    IncidentReport.source.url == url_payload.url
                )
                if exist:
                    return {
                        "status": "duplicate",
                        "report": exist.model_dump(),
                        "message": "Incident report already exists for this URL.",
                    }
            raise HTTPException(
                status_code=409,
                detail="Duplicate key error occurred but could not find existing document.",
            )
        except Exception as e:
            print(f"Unexpected error in create_incident_report: {e}")
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while processing the request.",
            )
    elif content_type and content_type.startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")

        if not file or not isinstance(file, UploadFile):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A 'file' part is required for multipart/form-data.",
            )
        # TODO complete PDF/file pipeline
        return {"status": "success", "source": "file", "filename": file.filename}
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported Content-Type: {content_type}. Must be 'application/json' or 'multipart/form-data'",
        )


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
