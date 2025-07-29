from fastapi import APIRouter, Body, Depends, Request, Response, HTTPException, status
from fastapi.encoders import jsonable_encoder
from typing import List
from pydantic import BaseModel
from app.dspy_files.newsAnalysis import run_full_analysis_from_url
from app.models.iuu_models import IncidentReport
import app.incident_logic

router = APIRouter()


def get_news_analysis_tool():
    return app.incident_logic.news_analysis_service


class URLRequest(BaseModel):
    url: str


@router.post("/incidents", response_model=IncidentReport, status_code=201)
async def create_incident_report(request: URLRequest):
    """
    Submits a URL for analysis and saves the resulting incident report to database.
    """
    saved_report = await app.incident_logic.create_report_from_url(request.url)

    if not saved_report:
        raise HTTPException(
            status_code=422,
            detail="Failed to process the URL or save the report. The source may be invalid or no relevant information was found.",
        )

    return saved_report


@router.get("/incidents/", response_model=List[IncidentReport])
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
