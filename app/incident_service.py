import os
from fastapi import File, HTTPException, status
from app.models.incidents import IncidentReport
from app.models.logs import LogContext
from app.dspy_files.news_analysis import AnalysisOrchestrator, PipelineResult
import logging

logger = logging.getLogger(__name__)


def _filter_valid_fields(model_class, updates: dict) -> dict:
    valid_fields = set(model_class.model_fields.keys())
    return {k: v for k, v in updates.items() if k in valid_fields}


class IncidentService:
    """
    Service layer for incident reports. Allows for greater logging
    """

    @staticmethod
    async def create_report_from_url(url: str) -> IncidentReport:
        # context = LogContext(
        #     user_id=context_data.get("acting_user_id"),
        #     action="new_report",
        #     source=context_data.get("source"),
        # )

        logger.info(f"Starting analysis for URL: {url}")
        api = os.getenv("OPENAI_API_KEY")
        orchestrator = AnalysisOrchestrator(api_key=api)
        output = await orchestrator.run_full_analysis_from_url(url=url)

        source = output.source
        report_object = output.incident
        if not source:
            logger.info(f"Analysis failed to produce a source for URL: {url}")
            return None

        if not report_object:
            logger.error(f"Analysis failed to produce a report for URL: {url}")
            return None

        if output.status != PipelineResult.SUCCESS:
            logger.error(f"Analysis failed for URL {url} with status {output.status}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Analysis failed with status: {output.status}: {output.error_message or 'No error message provided'}",
            )

        try:
            await source.insert()
            logger.info(f"Successfully saved source: {url}")
            await report_object.insert()
            logger.info(f"Successfully saved report for URL: {url}")
        except Exception as e:
            logger.error(f"Database save failed for URL {url}: {e}")
            return None
        await report_object.add_source(source, is_primary=True)
        return report_object

    @staticmethod
    async def create_report_from_file(file: File, context_data: dict) -> IncidentReport:
        context = LogContext(
            user_id=context_data.get("acting_user_id"),
            action="new_report",
            source=context_data.get("source"),
        )

        logger.info(f"Starting analysis for file: {file.filename}")
        return {"status": "error", "detail": "not implemented yet"}

    @staticmethod
    async def update_report(report_id: str, update_data: dict) -> IncidentReport:
        # context = LogContext(
        #     user_id=context_data.get("acting_user_id"),
        #     action="edit_report",
        #     source=context_data.get("source"),
        # )

        logger.info(f"Updating report {report_id} with data: {update_data}")

        report = await IncidentReport.get(report_id)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID {report_id} not found.",
            )

        # report.set_log_context(context)
        updates = _filter_valid_fields(IncidentReport, update_data)
        for field, value in updates.items():
            setattr(report, field, value)

        # report.set_log_context(context)

        try:
            await report.save()
            logger.info(f"Successfully updated report {report_id}")
        except Exception as e:
            logger.error(f"Update failed for report {report_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update the report.",
            )

        return report

    @staticmethod
    async def delete_report(report_id: str) -> bool:
        # context = LogContext(
        #     user_id=context_data.get("acting_user_id"),
        #     action="delete_report",
        #     source=context_data.get("source"),
        # )

        logger.info(f"Deleting report {report_id}")

        report = await IncidentReport.get(report_id)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID {report_id} not found.",
            )

        # report.set_log_context(context)

        try:
            await report.delete()
            logger.info(f"Successfully deleted report {report_id}")
        except Exception as e:
            logger.error(f"Deletion failed for report {report_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete the report.",
            )
        return True
