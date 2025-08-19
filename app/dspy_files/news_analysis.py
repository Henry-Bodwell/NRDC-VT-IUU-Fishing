from __future__ import annotations
from enum import Enum
import traceback
from typing import List

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
    FAILED_EXTRACTION = "failed_extraction"
    FAILED_CLASSIFICATION = "failed_classification"
    FAILED_ANALYSIS = "failed_analysis"
    FAILED_FORMATTING = "failed_formatting"
    UNRELATED_CONTENT = "unrelated_content"


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
    def has_incident(self) -> bool:
        return len(self.incidents) != 0

    @property
    def has_overview(self) -> bool:
        return self.industry_overview is not None


class AnalysisOrchestrator:
    def __init__(self, api_key: str):
        self.extractor = ContentExtractor(api_key=api_key)
        self.pipeline = AnalysisPipeline(api_key=api_key)

    async def run_full_analysis_from_url(self, url: str) -> PipelineOutput:
        """
        Orchestrates the end-to-end process of URL -> Text -> Analysis -> Format -> Verify.
        """

        try:
            logging.info(f"Starting analysis for: {url}")
            source = await self.extractor.from_url(url)
        except Exception as e:
            logging.error(f"Content Extraction failed for {url}: {e}")
            return PipelineOutput(
                status=PipelineResult.FAILED_EXTRACTION, error_message=str(e)
            )
        try:
            prediction = await self.pipeline.run(source)
            if not prediction:
                return PipelineOutput(
                    status=PipelineResult.FAILED_ANALYSIS,
                    sources=source,
                    error_message="Anaysis Pipeline returned no result",
                )
        except Exception as e:
            logging.error(f"Analysis failed for {url}: {e}")
            return PipelineOutput(
                status=PipelineResult.FAILED_ANALYSIS,
                source=source,
                error_message=str(e),
            )

        try:
            scope = source.article_scope.articleType
            if scope == "Unrelated to IUU Fishing":
                logger.info(f"Article from {url} is unrelated to IUU fishing")
                return PipelineOutput(
                    status=PipelineResult.UNRELATED_CONTENT, source=source
                )
            elif scope == "Industry Overview":
                logger.info(f"Article from {url} is an industry overview")
                logger.debug(
                    f"prediction.parsed_data type: {type(prediction.parsed_data)}"
                )

                try:
                    overview = IndustryOverview(
                        source=source,
                        extracted_information=prediction.parsed_data,
                    )
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
                    raise  # Re-raise to be caught by outer exception handler
            elif scope == "Multiple Incidents":
                logger.info(f"Article from {url} contains multiple incidents")
                incident_list = []
                for incident in prediction.incidents:
                    sub_prediction = dspy.Prediction(
                        sources=[source],
                        incident_classification=incident.classification,
                        parsed_data=incident.parsed_data,
                    )
                    processed = await self._process_incident_prediction(
                        sub_prediction, source
                    )
                    if not processed:
                        logger.error(
                            f"Failed to process incident prediction for {incident.parsed_data}"
                        )
                    incident_list.append(processed)
                return PipelineOutput(
                    status=PipelineResult.SUCCESS,
                    source=source,
                    incidents=incident_list,
                )

            elif scope == "Single Incident":
                incident = await self._process_incident_prediction(prediction, source)
                if not incident:
                    logger.error(f"Failed to process incident prediction for {url}")
                    return PipelineOutput(
                        status=PipelineResult.FAILED_FORMATTING,
                        source=source,
                        error_message="Failed to format incident report",
                    )

                logger.info(f"Successfully created incident report for {url}")
                return PipelineOutput(
                    status=PipelineResult.SUCCESS,
                    source=source,
                    incidents=[incident],
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
