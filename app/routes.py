from fastapi import APIRouter, Body, Depends, Request, Response, HTTPException, status
from fastapi.encoders import jsonable_encoder
from typing import List
from pydantic import BaseModel
from app.dspy_files.NewsAnalysisTool import NewsAnalysisTool
from app.models.iuu_models import IncidentReport
import app.incident_logic 


router = APIRouter()

def get_news_analysis_tool():
    return app.incident_logic.news_analysis_service

class URLRequest(BaseModel):
    url: str

@router.post("/incidents", response_model=IncidentReport)
async def create_incident_report(
    request: URLRequest,
    tool: NewsAnalysisTool = Depends(get_news_analysis_tool)
):
    """
    Creates, saves, and returns a new incident report from a URL.
    """

    
    report_object = await app.incident_logic.analyze_url_for_report(request.url, tool)
    
    throw_exception(report_object)

    saved_report = await app.incident_logic.save_report(report_object)

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