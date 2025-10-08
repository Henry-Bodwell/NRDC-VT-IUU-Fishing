from __future__ import annotations
from enum import Enum
import traceback
from typing import List, Optional, Callable, Awaitable

import dspy
from pydantic import BaseModel, Field
from app.dspy_files.content_extraction import ContentExtractor
from app.dspy_files.analysis_pipeline import AnalysisPipeline
from app.dspy_files.postprocessing import format_report
from app.models.articles import Source
from app.models.incidents import IncidentReport, IndustryOverview

import logging

logger = logging.getLogger(__name__)


class PipelineResult(Enum):
    """Enum for pipeline result status"""

    SUCCESS = "success"
    INVALID_INPUT = "invalid_input"
    FAILED_EXTRACTION = "failed_extraction"
    FAILED_CLASSIFICATION = "failed_classification"
    FAILED_ANALYSIS = "failed_analysis"
    FAILED_FORMATTING = "failed_formatting"
    UNRELATED_CONTENT = "unrelated_content"
    DUPLICATE_HASHED_TEXT = "duplicate_hashed_text"


class PipelineOutput(BaseModel):
    """Structured output from the pipeline"""

    status: PipelineResult
    source: Source | None = None
    incidents: List[IncidentReport] = Field(default_factory=list)
    industry_overview: IndustryOverview | None = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == PipelineResult.SUCCESS

    @property
    def is_unrelated(self) -> bool:
        return self.status == PipelineResult.UNRELATED_CONTENT

    @property
    def has_incident(self) -> bool:
        return len(self.incidents) != 0

    @property
    def has_overview(self) -> bool:
        return self.industry_overview is not None


class AnalysisOrchestrator:
    def __init__(self, api_key: str):
        self.extractor = ContentExtractor(api_key=api_key)
        self.pipeline = AnalysisPipeline(api_key=api_key)

    async def run_full_analysis_from_url(
        self,
        url: str,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> PipelineOutput:
        """
        Orchestrates the end-to-end process of URL -> Text -> Analysis -> Format -> Verify.

        Args:
            url: The URL to analyze
            progress_callback: Optional async callback(stage: str, percent: int) for progress updates
        """

        try:
            logging.info(f"Starting analysis for: {url}")

            # Stage 1: Content extraction (0-20%)
            if progress_callback:
                await progress_callback("content_extraction", 10)

            source = await self.extractor.from_url(url)

            if progress_callback:
                await progress_callback("content_extraction", 20)

            existing_source = await Source.find_one(
                {"article_hash": source.article_hash}
            )
            if existing_source:
                logger.info(f"Source already exists: {existing_source.id}")
                return PipelineOutput(
                    status=PipelineResult.DUPLICATE_HASHED_TEXT,
                    source=existing_source,
                    error_message="Duplicate Article",
                )
        except Exception as e:
            logging.error(f"Content Extraction failed for {url}: {e}")
            return PipelineOutput(
                status=PipelineResult.FAILED_EXTRACTION, error_message=str(e)
            )

        return await self.analysis_from_source(
            source=source, progress_callback=progress_callback
        )

    async def run_full_analysis_from_text(
        self,
        text: str,
        url: str | None = None,
        author: str | None = None,
        title: str | None = None,
        publisher: str | None = None,
        publication_date: str | None = None,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> PipelineOutput:
        """
        Orchestrates analysis from raw text.

        Args:
            text: The text to analyze
            url: Optional URL source
            author: Optional author name
            title: Optional title
            publisher: Optional publisher name
            publication_date: Optional publication date
            progress_callback: Optional async callback(stage: str, percent: int) for progress updates
        """
        if len(text) < 50:
            return PipelineOutput(
                status=PipelineResult.INVALID_INPUT,
                error_message="Text is too short to analyze",
            )
        try:
            logging.info(f"Starting analysis for: {text[:50]}...")

            # Stage 1: Content preparation (0-20%)
            if progress_callback:
                await progress_callback("content_extraction", 10)

            source = Source(
                article_text=text,
                url=url,
                article_title=title,
                author=author,
                publisher=publisher,
                publication_date=publication_date,
                category="text_upload",
            )

            if progress_callback:
                await progress_callback("content_extraction", 20)

            existing_source = await Source.find_one(
                {"article_hash": source.article_hash}
            )
            if existing_source:
                logger.info(f"Source already exists: {existing_source.id}")
                return PipelineOutput(
                    status=PipelineResult.DUPLICATE_HASHED_TEXT,
                    source=existing_source,
                    error_message="Duplicate Article",
                )

            logger.info(source.article_text[:50])
        except Exception as e:
            logging.error(f"Error creating source from: {text[:50]}... : {e}")
            return PipelineOutput(
                status=PipelineResult.FAILED_EXTRACTION, error_message=str(e)
            )
        return await self.analysis_from_source(
            source=source, progress_callback=progress_callback
        )

    async def analysis_from_source(
        self,
        source: Source,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> PipelineOutput:
        """
        Run analysis pipeline on a source document.

        Args:
            source: The source document to analyze
            progress_callback: Optional async callback(stage: str, percent: int) for progress updates
        """
        logger.info(
            f"Running analysis for source (article_hash): {source.article_hash}"
        )

        # Stage 2: Classification (20-40%)
        if progress_callback:
            await progress_callback("classification", 30)

        try:
            prediction = await self.pipeline.run(source)
            if not prediction:
                return PipelineOutput(
                    status=PipelineResult.FAILED_ANALYSIS,
                    sources=source,
                    error_message="Analysis Pipeline returned no result",
                )
        except Exception as e:
            logging.error(f"Analysis failed for {source.id}: {e}")
            return PipelineOutput(
                status=PipelineResult.FAILED_ANALYSIS,
                source=source,
                error_message=str(e),
            )

        if progress_callback:
            await progress_callback("classification", 40)

        # Stage 3: Analysis & Formatting (40-80%)
        if progress_callback:
            await progress_callback("analysis", 50)

        try:
            scope = source.article_scope.articleType
            if scope == "Unrelated to IUU Fishing":
                logger.info(f"Article from {source.id} is unrelated to IUU fishing")
                return PipelineOutput(
                    status=PipelineResult.UNRELATED_CONTENT, source=source
                )
            elif scope == "Industry Overview":
                return await self._process_industry_overview(
                    prediction, source, progress_callback
                )
            elif scope == "Multiple Incidents":
                return await self._process_multiple_incidents(
                    prediction, source, progress_callback
                )
            elif scope == "Single Incident":
                return await self._process_single_incident(
                    prediction, source, progress_callback
                )

        except Exception as e:
            error_details = {
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "traceback": traceback.format_exc(),
            }
            logger.error(f"Error processing prediction: {error_details}")

            return PipelineOutput(
                status=PipelineResult.FAILED_FORMATTING,
                source=source,
                error_message=f"{type(e).__name__}: {str(e)}",
            )

    async def _process_industry_overview(
        self,
        prediction: dspy.Prediction,
        source: Source,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> PipelineOutput:
        """Process industry overview prediction"""
        logger.info(f"Article from {source.id} is an industry overview")
        logger.debug(f"prediction.parsed_data type: {type(prediction.parsed_data)}")

        if progress_callback:
            await progress_callback("analysis", 60)

        try:
            overview = IndustryOverview(
                extracted_information=prediction.parsed_data,
            )
            source.overview = overview

            if progress_callback:
                await progress_callback("analysis", 80)

            logger.info(f"Successfully created overview: {overview}")
            return PipelineOutput(
                status=PipelineResult.SUCCESS,
                source=source,
                industry_overview=overview,
            )
        except Exception as e:
            logger.error(
                f"Error creating IndustryOverview: {type(e).__name__}: {str(e)}"
            )
            raise

    async def _process_multiple_incidents(
        self,
        prediction: dspy.Prediction,
        source: Source,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> PipelineOutput:
        """Process multiple incidents prediction"""
        logger.info(f"Article from {source.id} contains multiple incidents")

        if progress_callback:
            await progress_callback("analysis", 60)

        incident_list = []
        total_incidents = len(prediction.incidents)

        for idx, incident in enumerate(prediction.incidents):
            # incident is a dict with keys: 'sources', 'parsed_data', 'classification'
            sub_prediction = dspy.Prediction(
                sources=[source],
                incident_classification=incident.get("classification"),
                parsed_data=incident.get("parsed_data"),
            )
            processed = await self._process_incident_prediction(sub_prediction, source)
            if not processed:
                logger.error(
                    f"Failed to process incident prediction for {incident.get('parsed_data')}"
                )
            incident_list.append(processed)

            # Update progress incrementally (60-80%)
            if progress_callback and total_incidents > 0:
                progress = 60 + int((idx + 1) / total_incidents * 20)
                await progress_callback("analysis", progress)

        return PipelineOutput(
            status=PipelineResult.SUCCESS,
            source=source,
            incidents=incident_list,
        )

    async def _process_single_incident(
        self,
        prediction: dspy.Prediction,
        source: Source,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> PipelineOutput:
        """Process single incident prediction"""
        if progress_callback:
            await progress_callback("analysis", 60)

        incident = await self._process_incident_prediction(prediction, source)

        if progress_callback:
            await progress_callback("analysis", 80)

        if not incident:
            logger.error(f"Failed to process incident prediction for {source.id}")
            return PipelineOutput(
                status=PipelineResult.FAILED_FORMATTING,
                source=source,
                error_message="Failed to format incident report",
            )

        logger.info(f"Successfully created incident report for {source.id}")
        return PipelineOutput(
            status=PipelineResult.SUCCESS,
            source=source,
            incidents=[incident],
        )

    async def _process_incident_prediction(
        self, prediction: dspy.Prediction, source: Source
    ) -> IncidentReport | None:
        """Process incident prediction into IncidentReport"""
        try:
            # Format the raw prediction into a structured report
            logger.info(f"Formatting report from source: {source.url}")
            incident = format_report(prediction)
            if not incident:
                logger.error(f"Failed to format prediction into incident report")
                return None

            return incident

        except Exception as e:
            logger.error(f"Error processing incident prediction: {e}")
            return None
