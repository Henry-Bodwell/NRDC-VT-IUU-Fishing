import dspy
from signatures import (
    TextToStructuredData,
    StructuredDataToClassification,
    IndustryOverviewSignature,
)
from app.models.iuu_models import BaseIntake


class IncidentAnalysisModule(dspy.Module):
    """Module to extract and classify IUU incidents from text."""

    def __init__(self):
        super().__init__()

        self.extractor = dspy.ChainOfThought(TextToStructuredData)
        self.classifier = dspy.ChainOfThought(StructuredDataToClassification)

    def forward(self, intake: BaseIntake) -> dict:
        """
        Extract structured information from the article text and classify the incident.
        """
        try:
            # Extract structured information
            extraction = self.extractor(intake=intake)

            structured_data_output = extraction.extracted_data

            # Classify the incident
            classification_pred = self.classifier(
                incident_summary=structured_data_output.description,
                structured_data=structured_data_output.model_dump_json(),
            )

            classification = classification_pred.classification
            return {
                "url": intake.url,
                "article_text": intake.article_text,
                "extraction": extraction,
                "parsed_data": structured_data_output,
                "classification": classification,
            }
        except Exception as e:
            raise Exception(f"Error during extraction and classification: {str(e)}")


class IndustryOverviewModule(dspy.Module):
    """Module to extract information from industry overview articles."""

    def __init__(self):
        super().__init__()
        self.extractor = dspy.ChainOfThought(IndustryOverviewSignature)

    def forward(self, intake: BaseIntake) -> dict:
        """
        Extract structured information from the industry overview article text.
        """
        try:
            extraction = self.extractor(intake=intake)

            return {
                "url": intake.url,
                "article_text": intake.article_text,
                "extraction": extraction,
                "parsed_data": extraction.extracted_data,
            }
        except Exception as e:
            raise Exception(f"Error during industry overview extraction: {str(e)}")
