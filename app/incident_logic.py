from fastapi import HTTPException, status
from app.models.iuu_models import IncidentReport
from app.dspy_files.NewsAnalysisTool import NewsAnalysisTool
import os

news_analysis_service = NewsAnalysisTool(api_key=os.getenv("OPENAI_API_KEY"))


async def analyze_url_for_report(
    url: str, tool: NewsAnalysisTool
) -> IncidentReport | None:
    """
    Calls the analysis tool to get a report object. This does NOT save to the DB.
    """
    report_object = await tool.extract_and_verify(url)
    # print(report_object)
    if isinstance(report_object, IncidentReport):
        print(True)
        return report_object
    print(False)
    return None


async def save_report(report: IncidentReport) -> IncidentReport:
    """
    Saves a given IncidentReport object to the database. Inserts if it doesn't exist.
    """
    await report.save()
    return report
