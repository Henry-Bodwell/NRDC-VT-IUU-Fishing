import dspy
from app.dspy_files.signatures import (
    TextToStructuredData,
    TextToClassification,
    IndustryOverviewSignature,
)
from app.models.articles import Source


class IncidentAnalysisModule(dspy.Module):
    """Module to extract and classify IUU incidents from text."""

    def __init__(self):
        super().__init__()

        self.extractor = dspy.ChainOfThought(TextToStructuredData)
        self.classifier = dspy.ChainOfThought(TextToClassification)

    async def aforward(self, source: Source) -> dict:
        """
        Extract structured information from the article text and classify the incident.
        """
        try:
            # Extract structured information
            extraction = await self.extractor.acall(source=source)

            structured_data_output = extraction.extracted_data

            # Classify the incident
            classification_pred = await self.classifier.acall(
                incident_text=source.article_text
            )

            classification = classification_pred.classification
            return {
                "sources": [source],
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

    async def aforward(self, source: Source) -> dict:
        """
        Extract structured information from the industry overview article text.
        """
        try:
            extraction = await self.extractor.acall(source=source)

            return {
                "source": source,
                "extraction": extraction,
                "parsed_data": extraction.extracted_data,
            }
        except Exception as e:
            raise Exception(f"Error during industry overview extraction: {str(e)}")
