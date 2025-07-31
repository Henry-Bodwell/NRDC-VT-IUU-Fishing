import dspy
from app.dspy_files.signatures import (
    TextToStructuredData,
    StructuredDataToClassification,
    IndustryOverviewSignature,
)
from app.models.incidents import BaseIntake


class IncidentAnalysisModule(dspy.Module):
    """Module to extract and classify IUU incidents from text."""

    def __init__(self):
        super().__init__()

        self.extractor = dspy.ChainOfThought(TextToStructuredData)
        self.classifier = dspy.ChainOfThought(StructuredDataToClassification)

    async def aforward(self, intake: BaseIntake) -> dict:
        """
        Extract structured information from the article text and classify the incident.
        """
        try:
            # Extract structured information
            extraction = await self.extractor.acall(intake=intake)

            structured_data_output = extraction.extracted_data

            # Classify the incident
            classification_pred = await self.classifier.acall(
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

    async def aforward(self, intake: BaseIntake) -> dict:
        """
        Extract structured information from the industry overview article text.
        """
        try:
            extraction = await self.extractor.acall(intake=intake)

            return {
                "url": intake.url,
                "article_text": intake.article_text,
                "extraction": extraction,
                "parsed_data": extraction.extracted_data,
            }
        except Exception as e:
            raise Exception(f"Error during industry overview extraction: {str(e)}")
