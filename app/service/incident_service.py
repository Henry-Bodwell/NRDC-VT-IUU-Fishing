import os
from fastapi import HTTPException, status
from app.models.incidents import IncidentReport
from app.models.sources import Source, ArticleScopeClassification
from app.models.task import TaskStatus
from pymongo.errors import DuplicateKeyError
from app.dspy_files.news_analysis import (
    AnalysisOrchestrator,
    PipelineOutput,
    PipelineResult,
)
import logging
from app.dspy_files.content_extraction import ContentExtractor
from app.service.service import Service
from app.audit.context import AuditContext

logger = logging.getLogger(__name__)


class IncidentService(Service):
    """
    Service layer for incident reports. Allows for greater logging
    """

    @staticmethod
    async def _create_report(output: PipelineOutput) -> PipelineResult:
        if output.status == PipelineResult.DUPLICATE_HASHED_TEXT:
            logger.info(f"Text already exists in db: {output.source.id}")
            return output

        source = output.source

        if not source:
            logger.error("Analysis failed to produce a source")
            logger.error(f"Pipeline status {output.status}: {output.error_message}")

            return output

        if output.status != PipelineResult.UNRELATED_CONTENT:
            incidents = output.incidents
            industry = output.industry_overview

            if not output.has_incident and not output.has_overview:
                logger.error(
                    f"Analysis failed to produce a report for source: {source.id}"
                )
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
                saved_incidents = []
                for incident in incidents:
                    try:
                        await incident.insert()
                        logger.info(
                            f"Successfully saved incident report: {incident.id}"
                        )
                        saved_incidents.append(incident)
                    except Exception as e:
                        logger.error(
                            f"Database save failed for report {incident.id}: {e}"
                        )
                        raise e
                source.incidents = saved_incidents
                output.incidents = saved_incidents
            if output.has_overview and industry:
                try:
                    await industry.insert()
                    logger.info(f"Successfully saved industry report: {industry.id}")
                    source.overview = industry
                except Exception as e:
                    logger.error(
                        f"Database save failed for industry report {industry.id}: {e}"
                    )
                    raise e

        try:
            await source.insert()
            logger.info(f"Successfully saved source: {source.id}")
        except DuplicateKeyError as e:
            logger.warning(
                f"Source with same content already exists (hash: {source.article_hash}). Fetching existing source."
            )
            # Fetch the existing source instead of failing
            existing_source = await Source.find_one(
                Source.article_hash == source.article_hash
            )
            if existing_source:
                output.source = existing_source
                output.status = PipelineResult.DUPLICATE_HASHED_TEXT
                logger.info(f"Using existing source: {existing_source.id}")
                if output.has_incident:
                    for incident in output.incidents:
                        logger.warning(
                            f"Deleting orphaned incident {incident.id} from duplicate source race"
                        )
                        await incident.delete()
                if output.has_overview and industry and hasattr(industry, "source"):
                    industry.source = existing_source
                    await industry.save()
                return output
            else:
                # This shouldn't happen, but handle it just in case
                logger.error(
                    f"DuplicateKeyError but couldn't find existing source: {e}"
                )
                raise e
        except Exception as e:
            logger.error(f"Database save failed for {source.id}: {e}")
            if output.has_incident:
                for incident in output.incidents:
                    logger.warning(
                        f"Source insert failed; deleting orphaned incident {incident.id}"
                    )
                    await incident.delete()
            if output.has_overview and industry and hasattr(industry, "source"):
                logger.warning(
                    f"Source insert failed; deleting orphaned industry overview {industry.id}"
                )
                await industry.delete()
            raise e

        if output.status == PipelineResult.UNRELATED_CONTENT:
            logger.info(f"Source {source.id} unrelated to IUU fishing")
            return output

        if output.has_incident:
            for incident in output.incidents:
                if incident.primary_source is None:
                    await incident.add_source(source, is_primary=True)
                else:
                    await incident.add_source(source, is_primary=False)

        if output.has_overview and industry and hasattr(industry, "source"):
            industry.source = source
            await industry.save()

        return output

    @staticmethod
    def _get_orchestrator() -> AnalysisOrchestrator:
        api = os.getenv("OPENAI_API_KEY")
        return AnalysisOrchestrator(api_key=api)

    @staticmethod
    async def create_report_from_url(url: str) -> PipelineOutput:

        logger.info(f"Starting analysis for URL: {url}")

        orchestrator = IncidentService._get_orchestrator()

        output = await orchestrator.run_full_analysis_from_url(url=url)

        results = await IncidentService._create_report(output)
        return results

    @staticmethod
    async def create_report_from_pdf(
        pdf_bytes: bytes, filename: str = "", context_data: dict = {}
    ) -> PipelineResult:

        logger.info(f"Starting analysis for file: {filename}")
        source = ContentExtractor.from_pdf(pdf_bytes)
        orchestrator = IncidentService._get_orchestrator()
        output = await orchestrator.analysis_from_source(source=source)

        results = await IncidentService._create_report(output=output)

        return results

    @staticmethod
    async def create_report_from_text(
        text: str,
        url: str = "",
        author: str = "",
        title: str = "",
        publisher: str = "",
        date=None,
        status: str = "user_input",
    ) -> PipelineResult:
        logger.info(f"Starting analysis for text: {text[:50]}")
        orchestrator = IncidentService._get_orchestrator()
        output = await orchestrator.run_full_analysis_from_text(
            text=text,
            url=url,
            author=author,
            title=title,
            publisher=publisher,
            publication_date=date,
            status=status,
        )

        results = await IncidentService._create_report(output)
        return results

    @staticmethod
    async def add_source_to_report(
        report_id: str, source_id: str, is_primary: bool = False
    ) -> IncidentReport:
        report = await IncidentReport.get(report_id, fetch_links=True)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID {report_id} not found",
            )

        source = await Source.get(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source with ID {source_id} not found",
            )

        await report.add_source(source, is_primary=is_primary)
        logger.info(f"Added source {source_id} to report {report_id}")
        # Re-fetch without links to avoid circular reference recursion during serialization
        return await IncidentReport.get(report_id, fetch_links=False)

    @staticmethod
    async def remove_source_from_report(
        report_id: str, source_id: str
    ) -> IncidentReport:
        report = await IncidentReport.get(report_id, fetch_links=True)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID {report_id} not found",
            )

        source = await Source.get(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source with ID {source_id} not found",
            )

        await report.remove_source(source)
        logger.info(f"Removed source {source_id} from report {report_id}")
        # Re-fetch without links to avoid circular reference recursion during serialization
        return await IncidentReport.get(report_id, fetch_links=False)

    @staticmethod
    async def update_report(report_id: str, update_data: dict) -> IncidentReport:
        return await Service.update_model(
            model_cls=IncidentReport,
            model_id=report_id,
            update_data=update_data,
            model_name="report",
        )

    @staticmethod
    async def delete_report(report_id: str) -> bool:
        return await Service.delete(
            model_cls=IncidentReport,
            model_id=report_id,
            model_name="report",
        )

    # ── Composable entry points ─────────────────────────────────────

    @staticmethod
    async def analyze_existing_source(
        source: Source,
        assumed_scope: str | None = None,
    ) -> PipelineOutput:
        """
        Run analysis on a pre-existing Source, optionally overriding its
        classification. Does NOT persist results -- call save_pipeline_output()
        on the returned PipelineOutput to save.

        Args:
            source: An existing Source object (may or may not be in the DB)
            assumed_scope: If provided, override source.article_scope.
                          One of: "Single Incident", "Multiple Incidents",
                          "Industry Overview", "Unrelated to IUU Fishing"

        Returns:
            PipelineOutput ready for persistence via save_pipeline_output()
        """
        if assumed_scope:
            source.article_scope = ArticleScopeClassification(
                articleType=assumed_scope,
                confidence=1.0,
            )

        orchestrator = IncidentService._get_orchestrator()
        return await orchestrator.analysis_from_source(source=source)

    @staticmethod
    async def save_pipeline_output(output: PipelineOutput) -> PipelineOutput:
        """
        Persist a PipelineOutput to the database.

        Handles inserting incidents, overview, and source; duplicate-race
        cleanup; and relationship linking.
        """
        return await IncidentService._create_report(output)

    @staticmethod
    async def run_analysis_with_task_tracking(
        task_id: str,
        input_type: str,
        **kwargs,
    ):
        """
        Wrapper that runs the analysis pipeline with task progress tracking.

        Args:
            task_id: The task ID to update with progress
            input_type: "url", "pdf", or "text"
            **kwargs: Arguments to pass to the appropriate create_report method
        """
        task = await TaskStatus.find_one(TaskStatus.task_id == task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        # Define progress callback that updates the task
        async def progress_callback(stage: str, percent: int):
            await task.update_progress(stage, percent)
            logger.info(f"Task {task_id}: {stage} - {percent}%")

        try:
            logger.info(f"Task {task_id}: Starting analysis")

            # Get orchestrator
            orchestrator = IncidentService._get_orchestrator()

            # Run analysis with progress callback (handles 0-80% progress)
            if input_type == "url":
                output = await orchestrator.run_full_analysis_from_url(
                    url=kwargs["url"], progress_callback=progress_callback
                )
            elif input_type == "pdf":
                source = ContentExtractor.from_pdf(kwargs["pdf_bytes"])

                # Apply metadata to the source if provided
                if "title" in kwargs and kwargs["title"]:
                    source.article_title = kwargs["title"]
                if "author" in kwargs and kwargs["author"]:
                    source.author = kwargs["author"]
                if "publisher" in kwargs and kwargs["publisher"]:
                    source.publisher = kwargs["publisher"]
                if "publication_date" in kwargs and kwargs["publication_date"]:
                    source.publication_date = kwargs["publication_date"]
                if "url" in kwargs and kwargs["url"]:
                    source.url = kwargs["url"]
                if "status" in kwargs and kwargs["status"]:
                    source.status = kwargs["status"]
                if "input_name" in kwargs and kwargs["input_name"]:
                    source.input_name = kwargs["input_name"]

                output = await orchestrator.analysis_from_source(
                    source=source, progress_callback=progress_callback
                )
            elif input_type == "text":
                output = await orchestrator.run_full_analysis_from_text(
                    text=kwargs["text"],
                    url=kwargs.get("url", None),
                    author=kwargs.get("author", None),
                    title=kwargs.get("title", None),
                    publisher=kwargs.get("publisher", None),
                    publication_date=kwargs.get("date", None),
                    status=kwargs.get("status", "user_input"),
                    input_name=kwargs.get("input_name", None),
                    progress_callback=progress_callback,
                )
            else:
                raise ValueError(f"Invalid input_type: {input_type}")

            # Set source_type if provided
            if "source_type" in kwargs and output.source:
                output.source.source_type = kwargs["source_type"]

            # Stage: Saving to database (80-90%)
            await progress_callback("saving", 85)
            logger.info(f"Task {task_id}: Saving to database")

            # Get user_id from task and set audit context
            user_id = task.user_id if task.user_id else "anonymous"
            with AuditContext.with_user(user_id):
                results = await IncidentService._create_report(output)

            await progress_callback("saving", 95)

            # Stage 6: Check if pipeline succeeded
            result_data = {
                "status": results.status,
                "source_id": str(results.source.id) if results.source else None,
                "incident_ids": (
                    [str(i.id) for i in results.incidents] if results.incidents else []
                ),
                "industry_overview_id": (
                    str(results.industry_overview.id)
                    if results.industry_overview
                    else None
                ),
                "article_scope": (
                    results.source.article_scope if results.source else None
                ),
                "error_message": results.error_message,
            }

            # Check if the pipeline actually succeeded
            if (
                results.is_success
                or results.is_unrelated
                or results.status == PipelineResult.DUPLICATE_HASHED_TEXT
            ):
                await task.mark_completed(result_data)
                logger.info(
                    f"Task {task_id}: Completed successfully with status {results.status}"
                )
            else:
                # Pipeline failed - mark task as failed
                error_msg = (
                    results.error_message
                    or f"Pipeline failed with status: {results.status}"
                )
                await task.mark_failed(error_msg)
                logger.error(
                    f"Task {task_id}: Failed with status {results.status}: {error_msg}"
                )

        except Exception as e:
            logger.error(f"Task {task_id} failed with error: {str(e)}")
            await task.mark_failed(str(e))
            raise
