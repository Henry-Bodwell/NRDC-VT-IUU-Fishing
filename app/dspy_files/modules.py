import dspy
import logging
from app.dspy_files.signatures import (
    MultipleIncidentSignature,
    MultipleIncidentToStructured,
    TextToStructuredData,
    IndustryOverviewSignature,
    InformationPresenceSignature,
    InformationPresence,
    IdentifyIncidentAnchors,
    ConsolidateIncidents,
    ExtractVesselData,
    ExtractCrewData,
    ExtractLaborStandards,
    ExtractCatchData,
    ExtractComplianceData,
    ExtractSpeciesData,
    ExtractEventData,
    ExtractTransshipmentData,
    ExtractAquacultureData,
    ExtractTradeDistributionData,
    ExtractProductData,
    ExtractIUUClassification,
    SummarizeIncident,
)
from app.models.sources import Source
from app.rag.chunking import chunk_text
from app.rag.retrieval import join_chunks, retrieve_chunks
from app.rag.incident_segmentation import segment_incidents
from app.rag.vector_store import source_scope_key

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

        # RAG multi-incident segmentation (map/reduce over chunks)
        self.anchor_mapper = dspy.ChainOfThought(IdentifyIncidentAnchors)
        self.incident_reducer = dspy.ChainOfThought(ConsolidateIncidents)

        # Focused extractors (conditional based on presence)
        self.extract_vessel = dspy.ChainOfThought(ExtractVesselData)
        self.extract_crew = dspy.ChainOfThought(ExtractCrewData)
        self.extract_labor_standards = dspy.ChainOfThought(ExtractLaborStandards)
        self.extract_catch = dspy.ChainOfThought(ExtractCatchData)
        self.extract_compliance = dspy.ChainOfThought(ExtractComplianceData)
        self.extract_species = dspy.ChainOfThought(ExtractSpeciesData)
        self.extract_event = dspy.ChainOfThought(ExtractEventData)
        self.extract_transshipment = dspy.ChainOfThought(ExtractTransshipmentData)
        self.extract_aquaculture = dspy.ChainOfThought(ExtractAquacultureData)
        self.extract_trade_distribution = dspy.ChainOfThought(
            ExtractTradeDistributionData
        )
        self.extract_products = dspy.ChainOfThought(ExtractProductData)
        self.extract_classification = dspy.ChainOfThought(ExtractIUUClassification)
        self.summarize_incident = dspy.ChainOfThought(SummarizeIncident)

    async def aforward(
        self, source: Source, *, store=None, use_rag: bool = False
    ) -> dict:
        """
        Extract structured information from the article text and classify the incident.
        Uses two-stage approach: detect presence, then conditionally extract.

        When ``use_rag`` is set and a ``store`` (VectorStore) is supplied, the
        document is treated as large: extractors receive retrieved chunks instead
        of the full article, and multiple incidents are discovered via map/reduce
        segmentation rather than full-article regurgitation.
        """
        try:
            if use_rag and store is not None:
                return await self._aforward_rag(source, store)

            # Step 1: Detect information presence
            logger.info(
                f"Detecting information presence in article '{source.article_hash}'"
            )
            presence_output = await self.presenceDetector.acall(
                text=source.article_text
            )
            presence = presence_output.presence

            logger.info(f"Information presence flags: {presence.model_dump()}")

            # Store presence information in source for debugging/analysis
            source.information_presence = presence.model_dump()

            # Step 2: Conditionally extract based on presence flags
            if source.article_scope.articleType == "Single Incident":
                extracted_data = await self._extract_conditionally(
                    source.article_text, presence
                )

                # Validate critical fields with DSPy assertions
                # self._validate_extraction(structured_data_output, source.article_text)

                return {
                    "sources": [source],
                    "parsed_data": extracted_data,
                    "classification": extracted_data.get("classification"),
                    "presence": presence,
                }
            elif source.article_scope.articleType == "Multiple Incidents":
                split_result = await self.multiIncidentText.acall(
                    text=source.article_text
                )
                incident_passages = split_result.incident_passages
                source.incident_passages = incident_passages

                return_object = []
                for passage in incident_passages:
                    # Detect presence for each incident's target passage
                    incident_presence_output = await self.presenceDetector.acall(
                        text=passage.target_passage
                    )
                    incident_presence = incident_presence_output.presence

                    # Create combined text with clear instructions
                    # This gives the LLM both the specific incident passage and full context
                    combined_text = self._create_multi_incident_extraction_text(
                        passage.target_passage, passage.full_context
                    )

                    # Extract from the combined text, passing the target_passage for summary
                    extracted_data = await self._extract_conditionally(
                        combined_text,
                        incident_presence,
                        summary_text=passage.target_passage,
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

    @staticmethod
    def _all_present() -> InformationPresence:
        """Presence flags with everything enabled.

        In RAG mode we run every extractor and skip the separate
        presence-detection LLM call.

        Note this is not a true gate: top-k retrieval always returns k chunks
        when the document has them, however irrelevant, so an extractor whose
        category is absent still receives text and may confabulate rather than
        return empty. Retrieval scores are logged (see ``_resolve_text``) to
        establish whether a relevance floor can serve as the real gate.
        """
        return InformationPresence(
            has_vessel_info=True,
            has_crew_info=True,
            has_labor_standards=True,
            has_catch_info=True,
            has_compliance_info=True,
            has_species_info=True,
            has_event_details=True,
            has_transshipment=True,
            has_aquaculture=True,
            has_trade_distribution=True,
            has_iuu_classification=True,
        )

    async def _aforward_rag(self, source: Source, store) -> dict:
        """Retrieval extraction path, used for every source that indexed.

        Single Incident: each extractor pulls its own category-scoped chunks.
        Multiple Incidents: discover distinct incidents by map/reduce over chunks,
        then extract each incident from its own retrieved context -- never the
        whole article.
        """
        scope_key = source_scope_key(source)
        presence = self._all_present()
        source.information_presence = {"rag_mode": True}

        if source.article_scope.articleType == "Single Incident":
            logger.info(f"RAG single-incident extraction for '{source.article_hash}'")
            extracted_data = await self._extract_conditionally(
                "", presence, store=store, source_id=scope_key
            )
            return {
                "sources": [source],
                "parsed_data": extracted_data,
                "classification": extracted_data.get("classification"),
                "presence": presence,
            }

        # Multiple Incidents
        logger.info(f"RAG multi-incident segmentation for '{source.article_hash}'")
        chunks = chunk_text(source.article_text)
        descriptors = await segment_incidents(
            chunks, mapper=self.anchor_mapper, reducer=self.incident_reducer
        )
        logger.info(f"Segmented {len(descriptors)} incident(s)")

        return_object = []
        for descriptor in descriptors:
            # Each extractor retrieves its own category-scoped chunks, narrowed
            # to this incident by the descriptor's query. Retrieving once per
            # incident and reusing that context for all categories would hand
            # every extractor the same chunks and defeat per-category retrieval.
            extracted_data = await self._extract_conditionally(
                "",
                presence,
                summary_text=descriptor.description,
                store=store,
                source_id=scope_key,
                incident_query=descriptor.retrieval_query,
            )
            return_object.append(
                {
                    "sources": [source],
                    "parsed_data": extracted_data,
                    "classification": extracted_data.get("classification"),
                }
            )

        return {"incidents": return_object, "presence": presence}

    def _create_multi_incident_extraction_text(
        self, target_passage: str, full_context: str
    ) -> str:
        """
        Combines target passage and full context with clear extraction instructions.

        This format tells the LLM:
        1. Focus on extracting information about entities mentioned in the TARGET PASSAGE
        2. Use FULL CONTEXT only for supporting details (dates, locations, etc.)
        """
        return f"""EXTRACTION INSTRUCTIONS:
        Extract information ONLY about entities (vessels, people, events, species, products) that are mentioned in the TARGET PASSAGE below.

        If supporting details (like dates, locations, regulatory agencies, etc.) are mentioned elsewhere in the FULL CONTEXT, you may use them to enrich the extraction - but ONLY for entities found in the TARGET PASSAGE.

        Do NOT extract information about entities that appear only in the FULL CONTEXT but not in the TARGET PASSAGE.

        ===== TARGET PASSAGE (Extract from THIS incident) =====
        {target_passage}

        ===== FULL CONTEXT (Use only for supporting details) =====
        {full_context}
        """

    async def _resolve_text(
        self,
        category: str,
        default_text: str,
        store,
        source_id,
        k: int,
        incident_query: str | None = None,
    ) -> str:
        """Return the text fed to an extractor for ``category``.

        In RAG mode (store + source_id supplied) this is the retrieved,
        category-scoped context; otherwise it is ``default_text`` unchanged so
        the full-text fallback path behaves exactly as before.

        ``incident_query`` narrows retrieval to a single incident within a
        multi-incident document.
        """
        if store is None or source_id is None:
            return default_text

        chunks = await retrieve_chunks(
            store, source_id, category, k, extra_query=incident_query
        )
        # Scores are logged, not gated on: cosine similarity from
        # text-embedding-3-small is not absolutely calibrated, so a fixed floor
        # would silently suppress valid extractions. Collect data first, then
        # decide whether a relevance floor can replace presence detection.
        scores = [c.score for c in chunks if c.score is not None]
        best = f"{max(scores):.4f}" if scores else "n/a"
        logger.info(
            f"Retrieved {len(chunks)} chunk(s) for category '{category}' "
            f"(best score: {best})"
        )
        return join_chunks(chunks)

    async def _extract_conditionally(
        self,
        text: str,
        presence,
        summary_text: str = None,
        *,
        store=None,
        source_id=None,
        k: int = 5,
        incident_query: str | None = None,
    ) -> dict:
        """
        Extract information conditionally based on presence flags.
        Only runs extractors for categories that are detected as present.

        Args:
            text: The full text to extract from (may include extraction instructions).
                  Ignored per-category when ``store``/``source_id`` are supplied.
            presence: Information presence flags
            summary_text: Optional separate text to use for the description/summary field.
                         If not provided, uses the first 200 chars of text.
            store: Optional VectorStore for category-scoped retrieval (RAG mode).
            source_id: Retrieval-scoping key for the source (RAG mode).
            k: Number of chunks to retrieve per category (RAG mode).
            incident_query: Narrows retrieval to one incident within a
                            multi-incident document (RAG mode).
        """
        extracted = {}

        async def resolve(category: str) -> str:
            """Text for ``category``: retrieved in RAG mode, ``text`` otherwise."""
            return await self._resolve_text(
                category, text, store, source_id, k, incident_query
            )

        # Extract vessel info (if present)
        if presence.has_vessel_info:
            logger.info("Extracting vessel information...")
            vessel_text = await resolve("vessel")
            vessel_output = await self.extract_vessel.acall(text=vessel_text)
            extracted["vesselInformation"] = vessel_output.vessel_data
        else:
            logger.info("Skipping vessel extraction (not present)")
            extracted["vesselInformation"] = None

        # Extract crew info (if present)
        if presence.has_crew_info:
            logger.info("Extracting crew information...")
            crew_text = await resolve("crew")
            crew_output = await self.extract_crew.acall(text=crew_text)
            extracted["crewInformation"] = crew_output.crew_data
        else:
            logger.info("Skipping crew extraction (not present)")
            extracted["crewInformation"] = None

        # Extract labor standards (if present)
        if presence.has_labor_standards:
            logger.info("Extracting labor standards information...")
            labor_text = await resolve("labor")
            labor_output = await self.extract_labor_standards.acall(text=labor_text)
            extracted["laborStandards"] = labor_output.labor_standards
        else:
            logger.info("Skipping labor standards extraction (not present)")
            extracted["laborStandards"] = None

        # Extract catch info (if present)
        if presence.has_catch_info:
            logger.info("Extracting catch information...")
            catch_text = await resolve("catch")
            catch_output = await self.extract_catch.acall(text=catch_text)
            extracted["catchInformation"] = catch_output.catch_data
        else:
            logger.info("Skipping catch extraction (not present)")
            extracted["catchInformation"] = None

        # Extract compliance info (if present)
        if presence.has_compliance_info:
            logger.info("Extracting compliance information...")
            compliance_text = await resolve("compliance")
            compliance_output = await self.extract_compliance.acall(
                text=compliance_text
            )
            extracted["complianceInformation"] = compliance_output.compliance_data
        else:
            logger.info("Skipping compliance extraction (not present)")
            extracted["complianceInformation"] = None

        # Extract species info (if present)
        if presence.has_species_info:
            logger.info("Extracting species information...")
            species_text = await resolve("species")
            species_output = await self.extract_species.acall(text=species_text)
            extracted["speciesInvolved"] = species_output.species_list
        else:
            logger.info("Skipping species extraction (not present)")
            extracted["speciesInvolved"] = []

        # Extract event info (if present)
        if presence.has_event_details:
            logger.info("Extracting event information...")
            event_text = await resolve("event")
            event_output = await self.extract_event.acall(text=event_text)
            extracted["eventData"] = event_output.event_data
        else:
            logger.info("Skipping event extraction (not present)")
            extracted["eventData"] = None

        # Extract transshipment info (if present)
        if presence.has_transshipment:
            logger.info("Extracting transshipment information...")
            transship_text = await resolve("transshipment")
            transship_output = await self.extract_transshipment.acall(
                text=transship_text
            )
            extracted["transshipmentInformation"] = transship_output.transshipment_data
        else:
            logger.info("Skipping transshipment extraction (not present)")
            extracted["transshipmentInformation"] = None

        # Extract aquaculture info (if present)
        if presence.has_aquaculture:
            logger.info("Extracting aquaculture information...")
            aqua_text = await resolve("aquaculture")
            aqua_output = await self.extract_aquaculture.acall(text=aqua_text)
            extracted["aquacultureInformation"] = aqua_output.aquaculture_data
        else:
            logger.info("Skipping aquaculture extraction (not present)")
            extracted["aquacultureInformation"] = None

        # Extract trade/distribution info (if present)
        if presence.has_trade_distribution:
            logger.info("Extracting trade/distribution information...")
            trade_text = await resolve("trade_distribution")
            trade_output = await self.extract_trade_distribution.acall(text=trade_text)
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
        products_text = await resolve("products")
        products_output = await self.extract_products.acall(text=products_text)
        extracted["productsInvolved"] = products_output.products

        # Always classify IUU type (this is analytical, not extraction)
        logger.info("Classifying IUU type...")
        classification_text = await resolve("classification")
        classification_output = await self.extract_classification.acall(
            text=classification_text
        )
        extracted["classification"] = classification_output.classification

        # Add other fields with defaults
        extracted["chainOfCustody"] = None
        extracted["sanitaryLicenseID"] = None

        # Generate a proper summary using DSPy
        # Use summary_text if provided (for multi-incident), otherwise summarize text
        logger.info("Generating incident summary...")
        if not summary_text:
            summary_input = await resolve("summary")
            summary_output = await self.summarize_incident.acall(text=summary_input)
            extracted["description"] = summary_output.summary
        else:
            extracted["description"] = summary_text[:400] + (
                "..." if len(summary_text) > 400 else ""
            )

        return extracted

    def _validate_extraction(self, extracted_data, text: str):
        """Validate that critical fields are extracted and log warnings"""
        if not extracted_data:
            logger.warning("Extracted data is None, skipping validation")
            return

        text_lower = text.lower() if text else ""

        # Check if text mentions fish/seafood/marine animals
        fish_keywords = [
            "fish",
            "tuna",
            "salmon",
            "shark",
            "shrimp",
            "lobster",
            "crab",
            "seafood",
            "vessel",
            "catch",
            "fishing",
            "marine",
            "ocean",
            "species",
            "aquatic",
            "shellfish",
            "squid",
            "anchovy",
            "sardine",
        ]
        mentions_fish = any(keyword in text_lower for keyword in fish_keywords)

        # Log warning if species missing when fish/seafood mentioned
        species_involved = getattr(extracted_data, "speciesInvolved", None)
        if mentions_fish and (species_involved is None or len(species_involved) == 0):
            logger.warning(
                "Text mentions fish/seafood but no species were extracted. "
                "Consider adding species information."
            )

        # Check for product mentions (fins, fillets, etc.)
        product_keywords = [
            "fin",
            "fillet",
            "steak",
            "meat",
            "product",
            "processed",
            "frozen",
            "canned",
            "dried",
            "smoked",
            "whole",
            "dressed",
        ]
        mentions_product = any(keyword in text_lower for keyword in product_keywords)

        # Log warning if products missing when species + products mentioned
        products_involved = getattr(extracted_data, "productsInvolved", None)
        if (
            species_involved
            and len(species_involved) > 0
            and mentions_product
            and (products_involved is None or len(products_involved) == 0)
        ):
            logger.warning(
                "Text mentions species and seafood products but productsInvolved is empty. "
                "Consider extracting product information."
            )

        # Log warning if vessel name missing when vessel mentioned
        vessel_keywords = ["vessel", "ship", "boat", "trawler", "seiner"]
        mentions_vessel = any(keyword in text_lower for keyword in vessel_keywords)

        vessel_info = getattr(extracted_data, "vesselInformation", None)
        if mentions_vessel and vessel_info:
            vessel_name = getattr(vessel_info, "vesselName", None)
            vessel_id = getattr(vessel_info, "vesselUniqueID", None)
            if not vessel_name and not vessel_id:
                logger.warning(
                    "Text mentions vessels but no vessel name or ID was extracted. "
                    "Consider adding vessel information."
                )

        # Log warning if event data is missing
        event_data = getattr(extracted_data, "eventData", None)
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
