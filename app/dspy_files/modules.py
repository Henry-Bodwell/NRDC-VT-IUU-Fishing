import dspy
from app.dspy_files.signatures import (
    MultipleIncidentSignature,
    MultipleIncidentToStructured,
    TextToStructuredData,
    IndustryOverviewSignature,
    InformationPresenceSignature,
    ExtractVesselData,
    ExtractCrewLaborData,
    ExtractCatchData,
    ExtractComplianceData,
    ExtractSpeciesData,
    ExtractEventData,
    ExtractTransshipmentData,
    ExtractAquacultureData,
    ExtractTradeDistributionData,
    ExtractProductData,
    ExtractIUUClassification,
)
from app.models.articles import Source
from app.models.incidents import ExtractedIncidentData
import logging

logger = logging.getLogger(__name__)


class IncidentAnalysisModule(dspy.Module):
    """Module to extract and classify IUU incidents from text."""

    def __init__(self):
        super().__init__()

        # Presence detection
        self.presenceDetector = dspy.ChainOfThought(InformationPresenceSignature)

        # Legacy extractors (for backward compatibility)
        self.extractAndClassify = dspy.ChainOfThought(TextToStructuredData)
        self.multiIncidentText = dspy.ChainOfThought(MultipleIncidentSignature)
        self.multiIncidentClass = dspy.ChainOfThought(MultipleIncidentToStructured)

        # Focused extractors (conditional based on presence)
        self.extract_vessel = dspy.ChainOfThought(ExtractVesselData)
        self.extract_crew_labor = dspy.ChainOfThought(ExtractCrewLaborData)
        self.extract_catch = dspy.ChainOfThought(ExtractCatchData)
        self.extract_compliance = dspy.ChainOfThought(ExtractComplianceData)
        self.extract_species = dspy.ChainOfThought(ExtractSpeciesData)
        self.extract_event = dspy.ChainOfThought(ExtractEventData)
        self.extract_transshipment = dspy.ChainOfThought(ExtractTransshipmentData)
        self.extract_aquaculture = dspy.ChainOfThought(ExtractAquacultureData)
        self.extract_trade_distribution = dspy.ChainOfThought(ExtractTradeDistributionData)
        self.extract_products = dspy.ChainOfThought(ExtractProductData)
        self.extract_classification = dspy.ChainOfThought(ExtractIUUClassification)

    async def aforward(self, source: Source) -> dict:
        """
        Extract structured information from the article text and classify the incident.
        Uses two-stage approach: detect presence, then conditionally extract.
        """
        try:
            # Step 1: Detect information presence
            logger.info(f"Detecting information presence in article '{source.article_hash}'")
            presence_output = await self.presenceDetector.acall(text=source.article_text)
            presence = presence_output.presence

            logger.info(f"Information presence flags: {presence.model_dump()}")

            # Store presence information in source for debugging/analysis
            source.information_presence = presence.model_dump()

            # Step 2: Conditionally extract based on presence flags
            if source.article_scope.articleType == "Single Incident":
                extracted_data = await self._extract_conditionally(
                    source.article_text, presence
                )

                return {
                    "sources": [source],
                    "parsed_data": extracted_data,
                    "classification": extracted_data.get("classification"),
                    "presence": presence,
                }
            elif source.article_scope.articleType == "Multiple Incidents":
                source.seperated_incident_text = await self.multiIncidentText.acall(
                    text=source.article_text
                )
                return_object = []
                for incident_text in source.seperated_incident_text.seperated_incident_text:
                    # Detect presence for each incident
                    incident_presence_output = await self.presenceDetector.acall(
                        text=incident_text
                    )
                    incident_presence = incident_presence_output.presence

                    extracted_data = await self._extract_conditionally(
                        incident_text, incident_presence
                    )

                    sub_out = {
                        "sources": [source],
                        "parsed_data": extracted_data,
                        "classification": extracted_data.get("classification"),
                    }
                    return_object.append(sub_out)

                return {"incidents": return_object, "presence": presence}

        except Exception as e:
            raise Exception(f"Error during extraction and classification: {str(e)}")

    async def _extract_conditionally(self, text: str, presence) -> dict:
        """
        Extract information conditionally based on presence flags.
        Only runs extractors for categories that are detected as present.
        """
        extracted = {}

        # Extract vessel info (if present)
        if presence.has_vessel_info:
            logger.info("Extracting vessel information...")
            vessel_output = await self.extract_vessel.acall(text=text)
            extracted["vesselInformation"] = vessel_output.vessel_data
        else:
            logger.info("Skipping vessel extraction (not present)")
            extracted["vesselInformation"] = None

        # Extract crew/labor info (if present)
        if presence.has_crew_labor_info:
            logger.info("Extracting crew/labor information...")
            crew_output = await self.extract_crew_labor.acall(text=text)
            extracted["crewLaborInformation"] = crew_output.crew_labor_data
        else:
            logger.info("Skipping crew/labor extraction (not present)")
            extracted["crewLaborInformation"] = None

        # Extract catch info (if present)
        if presence.has_catch_info:
            logger.info("Extracting catch information...")
            catch_output = await self.extract_catch.acall(text=text)
            extracted["catchInformation"] = catch_output.catch_data
        else:
            logger.info("Skipping catch extraction (not present)")
            extracted["catchInformation"] = None

        # Extract compliance info (if present)
        if presence.has_compliance_info:
            logger.info("Extracting compliance information...")
            compliance_output = await self.extract_compliance.acall(text=text)
            extracted["complianceInformation"] = compliance_output.compliance_data
        else:
            logger.info("Skipping compliance extraction (not present)")
            extracted["complianceInformation"] = None

        # Extract species info (if present)
        if presence.has_species_info:
            logger.info("Extracting species information...")
            species_output = await self.extract_species.acall(text=text)
            extracted["speciesInvolved"] = species_output.species_list
        else:
            logger.info("Skipping species extraction (not present)")
            extracted["speciesInvolved"] = []

        # Extract event info (if present)
        if presence.has_event_details:
            logger.info("Extracting event information...")
            event_output = await self.extract_event.acall(text=text)
            extracted["eventData"] = event_output.event_data
        else:
            logger.info("Skipping event extraction (not present)")
            extracted["eventData"] = None

        # Extract transshipment info (if present)
        if presence.has_transshipment:
            logger.info("Extracting transshipment information...")
            transship_output = await self.extract_transshipment.acall(text=text)
            extracted["transshipmentInformation"] = transship_output.transshipment_data
        else:
            logger.info("Skipping transshipment extraction (not present)")
            extracted["transshipmentInformation"] = None

        # Extract aquaculture info (if present)
        if presence.has_aquaculture:
            logger.info("Extracting aquaculture information...")
            aqua_output = await self.extract_aquaculture.acall(text=text)
            extracted["aquacultureInformation"] = aqua_output.aquaculture_data
        else:
            logger.info("Skipping aquaculture extraction (not present)")
            extracted["aquacultureInformation"] = None

        # Extract trade/distribution info (if present)
        if presence.has_trade_distribution:
            logger.info("Extracting trade/distribution information...")
            trade_output = await self.extract_trade_distribution.acall(text=text)
            extracted["tradeInformation"] = trade_output.trade_data
            extracted["distributionInformation"] = trade_output.distribution_data
            extracted["aggregationInformation"] = trade_output.aggregation_data
            extracted["landingInformation"] = trade_output.landing_data
        else:
            logger.info("Skipping trade/distribution extraction (not present)")
            extracted["tradeInformation"] = None
            extracted["distributionInformation"] = None
            extracted["aggregationInformation"] = None
            extracted["landingInformation"] = None

        # Extract product info (always try, but may return empty list)
        logger.info("Extracting product information...")
        products_output = await self.extract_products.acall(text=text)
        extracted["productsInvolved"] = products_output.products

        # Always classify IUU type (this is analytical, not extraction)
        logger.info("Classifying IUU type...")
        classification_output = await self.extract_classification.acall(text=text)
        extracted["classification"] = classification_output.classification

        # Add other fields with defaults
        extracted["chainOfCustody"] = None
        extracted["sanitaryLicenseID"] = None
        extracted["description"] = text[:200] + "..."  # Short summary

        return extracted


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
