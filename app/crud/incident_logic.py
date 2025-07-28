from fastapi import HTTPException, status
from app.models.iuu_models import IncidentReport
from app.dspy.NewsAnalysisTool import NewsAnalysisTool

news_analysis_service = NewsAnalysisTool()


async def analyze_url_for_report(
    url: str, tool: NewsAnalysisTool
) -> IncidentReport | None:
    """
    Calls the analysis tool to get a report object. This does NOT save to the DB.
    """
    report_object = await tool.extract_and_verify(url)
    if isinstance(report_object, IncidentReport):
        return report_object
    return None


async def save_report(report: IncidentReport) -> IncidentReport:
    """
    Saves a given IncidentReport object to the database. Inserts if it doesn't exist.
    """
    await report.save()
    return report
