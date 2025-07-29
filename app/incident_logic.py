from fastapi import HTTPException, status
from app.dspy_files.newsAnalysis import run_full_analysis_from_url
from app.models.iuu_models import IncidentReport


async def create_report_from_url(url: str) -> IncidentReport | None:
    """
    This is the service layer function. It contains the core business logic.
    It is completely independent of FastAPI.
    """
    print(f"Service: Starting analysis for URL: {url}")

    report_object = await run_full_analysis_from_url(url)

    if not report_object:
        print(f"Service: Analysis failed to produce a report for URL: {url}")
        return None

    try:
        await report_object.insert()
        print(f"Service: Successfully saved report for URL: {url}")
    except Exception as e:
        print(f"Service: Database save failed for URL {url}: {e}")
        return None

    return report_object
