from typing import List
import dspy
from app.dspy_files.config import setup_dspy
from app.dspy_files.source_scope import SourceScope
from app.models.articles import Source
from app.dspy_files.modules import IncidentAnalysisModule, IndustryOverviewModule
import logging

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """Orchestrates the analysis of an article by classifying and routing it."""

    def __init__(self, api_key, model="openai/gpt-4o-mini"):
        """Initialize the analysis pipeline with necessary tools."""
        self.lm = setup_dspy(model=model, api_key=api_key)

        self.source_scope = SourceScope()
        self.incident_analysis_tool = IncidentAnalysisModule()
        self.industry_overview_tool = IndustryOverviewModule()
        # self.optimized_analysisTool = None # Can be added later

    async def run(self, source: Source) -> dspy.Prediction:
        """
        Classifies the article and runs the appropriate analysis module.
        """
        try:
            if not source.article_scope:
                logger.info(f"Classifying article scope from '{source.url}'")
                source = await self.source_scope.run(source=source)

            article_type = source.article_scope.articleType
            logger.info(
                f"Processing article from '{source.url}' classified as: {article_type}"
            )

            if article_type == "Unrelated to IUU Fishing":
                return dspy.Prediction(
                    sources=[source],
                    extracted_data=None,
                )

            elif article_type == "Industry Overview":
                module_output = await self.industry_overview_tool.acall(source=source)
                return dspy.Prediction(
                    sources=[source],
                    parsed_data=module_output.get("parsed_data"),
                )
            elif article_type == "Multiple Incidents":
                module_output = await self.incident_analysis_tool.acall(source=source)
                return dspy.Prediction(
                    sources=[source],
                    incidents=module_output.get("incidents"),
                )
            else:  # "Single Incident"
                module_output = await self.incident_analysis_tool.acall(source=source)
                return dspy.Prediction(
                    sources=[source],
                    incident_classification=module_output.get("classification"),
                    parsed_data=module_output.get("parsed_data"),
                )

        except Exception as e:
            logger.error(f"Error during analysis pipeline for '{source.url}': {e}")
            raise
