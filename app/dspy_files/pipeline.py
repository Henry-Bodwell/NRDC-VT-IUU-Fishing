import dspy
from app.models.articles import BaseIntake
from app.dspy_files.modules import IncidentAnalysisModule, IndustryOverviewModule
from app.dspy_files.signatures import ArticleClassificationSignature


class AnalysisPipeline:
    """Orchestrates the analysis of an article by classifying and routing it."""

    def __init__(self):
        self.classification_tool = dspy.ChainOfThought(ArticleClassificationSignature)
        self.incident_analysis_tool = IncidentAnalysisModule()
        self.industry_overview_tool = IndustryOverviewModule()
        # self.optimized_analysisTool = None # Can be added later

    async def run(
        self, article_text: str, source_identifier: str = ""
    ) -> dspy.Prediction:
        """
        Classifies the article and runs the appropriate analysis module.
        """
        try:
            intake = BaseIntake(url=source_identifier, article_text=article_text)

            # 1. Classify the article
            classification_pred = await self.classification_tool.acall(intake=intake)
            classification_result = classification_pred.classification

            # 2. Route to the correct analysis tool based on classification
            article_type = classification_result.articleType
            print(f"Article from '{source_identifier}' classified as: {article_type}")

            if article_type == "Unrelated to IUU Fishing":
                # Return a prediction with source info and classification only
                return dspy.Prediction(
                    url=intake.url,
                    article_text=intake.article_text,
                    classification=classification_result,
                    extracted_data=None,  # Explicitly None
                )

            elif article_type == "Industry Overview":
                # Get the complete dictionary from your custom module
                module_output = await self.industry_overview_tool.acall(intake=intake)
                return dspy.Prediction(
                    url=module_output.get("url"),
                    article_text=module_output.get("article_text"),
                    classification=classification_result,
                    parsed_data=module_output.get("parsed_data"),
                )

            else:  # "IUU Incident Report", "Single Incident", etc.
                # Get the complete dictionary from your custom module
                module_output = await self.incident_analysis_tool.acall(intake=intake)
                return dspy.Prediction(
                    url=module_output.get("url"),
                    article_text=module_output.get("article_text"),
                    classification=module_output.get("classification"),
                    parsed_data=module_output.get("parsed_data"),
                )

        except Exception as e:
            print(f"Error during analysis pipeline for '{source_identifier}': {e}")
            return None
