import dspy
from app.dspy_files.signatures import (
    MultipleIncidentSignature,
    MultipleIncidentToStructured,
    TextToStructuredData,
    IndustryOverviewSignature,
)
from app.models.articles import Source


class IncidentAnalysisModule(dspy.Module):
    """Module to extract and classify IUU incidents from text."""

    def __init__(self):
        super().__init__()

        self.extractAndClassify = dspy.ChainOfThought(TextToStructuredData)
        self.multiIncidentText = dspy.ChainOfThought(MultipleIncidentSignature)
        self.multiIncidentClass = dspy.ChainOfThought(MultipleIncidentToStructured)

    async def aforward(self, source: Source) -> dict:
        """
        Extract structured information from the article text and classify the incident.
        """
        try:
            # Extract structured information
            if source.article_scope.articleType == "Single Incident":
                output = await self.extractAndClassify.acall(source=source)
                structured_data_output = output.extracted_data
                classification = output.classification

                return {
                    "sources": [source],
                    "parsed_data": structured_data_output,
                    "classification": classification,
                }
            elif source.article_scope.articleType == "Multiple Incidents":
                source.seperated_incident_text = await self.multiIncident.acall(
                    text=source.article_text
                )
                return_object = []
                for incident in source.seperated_incident_text:
                    output = await self.multiIncidentClass.acall(text=incident)
                    sub_out = {
                        "sources": [source],
                        "parsed_data": output.extracted_data,
                        "classification": output.classication,
                    }
                    return_object.append(sub_out)

                return {"incidents": return_object}

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
