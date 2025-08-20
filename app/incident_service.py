import os
from fastapi import File, HTTPException, status
from app.models.incidents import IncidentReport, IndustryOverview
from app.models.logs import LogContext
from app.dspy_files.news_analysis import (
    AnalysisOrchestrator,
    PipelineOutput,
    PipelineResult,
)
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
    async def _create_report(output: PipelineOutput) -> PipelineResult:
        source = output.source

        if not source:
            logger.error(f"Analysis failed to produce a source")
            logger.error(f"Pipeline status {output.status}: {output.error_message}")

            return output

        try:
            await source.insert()
            logger.info(f"Successfully saved source: {source.id}")
        except Exception as e:
            logger.error(f"Database save failed for {source.id}: {e}")
            raise e

        if output.status == PipelineResult.UNRELATED_CONTENT:
            logger.info(f"Source {source.id} unrelated to IUU fishing")
            return output

        incidents = output.incidents
        industry = output.industry_overview
        if not output.has_incident and not output.has_overview:
            logger.error(f"Analysis failed to produce a report for source: {source.id}")
            logger.error(f"Pipeline status {output.status}: {output.error_message}")
            return output

        if not output.is_success:
            logger.error(
                f"Analysis failed for source {source.id} with status {output.status}"
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Analysis failed with status: {output.status}: {output.error_message or 'No error message provided'}",
            )
        if output.has_incident:
            output.incidents = []
            for incident in incidents:
                try:
                    await incident.insert()
                    logger.info(f"Successfully saved incident report: {incident.id}")
                except Exception as e:
                    logger.error(f"Database save failed for report {incident.id}: {e}")
                    raise e
                await incident.add_source(source, is_primary=True)
                output.incidents.append(incident)
            return output
        else:
            try:
                await industry.insert()
                logger.info(f"Successfully saved industry report: {industry.id}")
            except Exception as e:
                logger.error(
                    f"Database save failed for industry report {industry.id}: {e}"
                )
                raise e
            output.industry_overview = industry
            return output

    @staticmethod
    def _get_orchestrator() -> AnalysisOrchestrator:
        api = os.getenv("OPENAI_API_KEY")
        return AnalysisOrchestrator(api_key=api)

    @staticmethod
    async def create_report_from_url(url: str) -> PipelineOutput:
        # context = LogContext(
        #     user_id=context_data.get("acting_user_id"),
        #     action="new_report",
        #     source=context_data.get("source"),
        # )

        logger.info(f"Starting analysis for URL: {url}")

        orchestrator = IncidentService._get_orchestrator()

        output = await orchestrator.run_full_analysis_from_url(url=url)

        results = await IncidentService._create_report(output)
        return results

    @staticmethod
    async def create_report_from_file(file: File, context_data: dict) -> PipelineResult:
        context = LogContext(
            user_id=context_data.get("acting_user_id"),
            action="new_report",
            source=context_data.get("source"),
        )

        logger.info(f"Starting analysis for file: {file.filename}")
        return {"status": "error", "detail": "not implemented yet"}

    @staticmethod
    async def create_report_from_text(text: str) -> PipelineResult:
        logger.info(f"Starting analysis for text: {text[:50]}")
        orchestrator = IncidentService._get_orchestrator()
        output = await orchestrator.run_full_analysis_from_text(text=text)

        results = await IncidentService._create_report(output)
        return results

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
