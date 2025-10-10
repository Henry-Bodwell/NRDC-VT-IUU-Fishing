import dspy
import logging
from app.dspy_files.signatures import (
    MultipleIncidentSignature,
    MultipleIncidentToStructured,
    TextToStructuredData,
    IndustryOverviewSignature,
)
from app.models.articles import Source

logger = logging.getLogger(__name__)


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

                # Check if output has extracted_data before validation
                if not hasattr(output, 'extracted_data') or output.extracted_data is None:
                    raise Exception(
                        "DSPy output missing extracted_data for single incident analysis"
                    )

                structured_data_output = output.extracted_data
                classification = output.classification

                # Validate critical fields with DSPy assertions
                self._validate_extraction(structured_data_output, source.article_text)

                return {
                    "sources": [source],
                    "parsed_data": structured_data_output,
                    "classification": classification,
                }
            elif source.article_scope.articleType == "Multiple Incidents":
                split_result = await self.multiIncidentText.acall(
                    text=source.article_text
                )
                separated_texts = split_result.seperated_incident_text
                source.seperated_incident_text = separated_texts

                return_object = []
                for incident_text in separated_texts:
                    output = await self.multiIncidentClass.acall(text=incident_text)

                    # Check if output has extracted_data before validation
                    if not hasattr(output, 'extracted_data') or output.extracted_data is None:
                        logger.error(
                            f"DSPy output missing extracted_data for incident text: {incident_text[:100]}..."
                        )
                        continue

                    # Validate critical fields with DSPy assertions
                    self._validate_extraction(output.extracted_data, incident_text)

                    sub_out = {
                        "sources": [source],
                        "parsed_data": output.extracted_data,
                        "classification": output.classification,
                    }
                    return_object.append(sub_out)

                return {"incidents": return_object}

        except Exception as e:
            raise Exception(f"Error during extraction and classification: {str(e)}")

    def _validate_extraction(self, extracted_data, text: str):
        """Validate that critical fields are extracted and log warnings"""
        if not extracted_data:
            logger.warning("Extracted data is None, skipping validation")
            return

        text_lower = text.lower() if text else ""

        # Check if text mentions fish/seafood/marine animals
        fish_keywords = [
            'fish', 'tuna', 'salmon', 'shark', 'shrimp', 'lobster', 'crab',
            'seafood', 'vessel', 'catch', 'fishing', 'marine', 'ocean',
            'species', 'aquatic', 'shellfish', 'squid', 'anchovy', 'sardine'
        ]
        mentions_fish = any(keyword in text_lower for keyword in fish_keywords)

        # Log warning if species missing when fish/seafood mentioned
        species_involved = getattr(extracted_data, 'speciesInvolved', None)
        if mentions_fish and (species_involved is None or len(species_involved) == 0):
            logger.warning(
                "Text mentions fish/seafood but no species were extracted. "
                "Consider adding species information."
            )

        # Check for product mentions (fins, fillets, etc.)
        product_keywords = [
            'fin', 'fillet', 'steak', 'meat', 'product', 'processed',
            'frozen', 'canned', 'dried', 'smoked', 'whole', 'dressed'
        ]
        mentions_product = any(keyword in text_lower for keyword in product_keywords)

        # Log warning if products missing when species + products mentioned
        products_involved = getattr(extracted_data, 'productsInvolved', None)
        if species_involved and len(species_involved) > 0 and mentions_product and (products_involved is None or len(products_involved) == 0):
            logger.warning(
                "Text mentions species and seafood products but productsInvolved is empty. "
                "Consider extracting product information."
            )

        # Log warning if vessel name missing when vessel mentioned
        vessel_keywords = ['vessel', 'ship', 'boat', 'trawler', 'seiner']
        mentions_vessel = any(keyword in text_lower for keyword in vessel_keywords)

        catch_source = getattr(extracted_data, 'catchSourceInformation', None)
        if mentions_vessel and catch_source:
            vessel_name = getattr(catch_source, 'vesselName', None)
            vessel_id = getattr(catch_source, 'vesselUniqueID', None)
            if not vessel_name and not vessel_id:
                logger.warning(
                    "Text mentions vessels but no vessel name or ID was extracted. "
                    "Consider adding vessel information."
                )

        # Log warning if event data is missing
        event_data = getattr(extracted_data, 'eventData', None)
        if not event_data:
            logger.warning(
                "No event data extracted. Consider extracting event category and resolution."
            )


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
