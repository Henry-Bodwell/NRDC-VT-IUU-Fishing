"""
Unit tests for modules.py - DSPy analysis modules.

Tests the IncidentAnalysisModule and IndustryOverviewModule classes which:
- Detect information presence in articles
- Conditionally extract data based on presence flags
- Handle single and multiple incident articles
- Extract industry overview information
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.sources import ArticleScopeClassification
from app.dspy_files.modules import IncidentAnalysisModule, IndustryOverviewModule


def create_mock_source(
    url: str = "https://example.com/test",
    article_text: str = "Test article about illegal fishing.",
    article_hash: str = "abc123hash",
    article_scope: ArticleScopeClassification | None = None,
):
    """Create a mock Source object."""
    mock_source = MagicMock()
    mock_source.url = url
    mock_source.article_text = article_text
    mock_source.article_hash = article_hash
    mock_source.article_scope = article_scope
    mock_source.information_presence = None
    mock_source.incident_passages = None
    return mock_source


def create_mock_presence(
    has_vessel_info: bool = False,
    has_crew_info: bool = False,
    has_labor_standards: bool = False,
    has_catch_info: bool = False,
    has_compliance_info: bool = False,
    has_species_info: bool = False,
    has_event_details: bool = False,
    has_transshipment: bool = False,
    has_aquaculture: bool = False,
    has_trade_distribution: bool = False,
    has_iuu_classification: bool = False,
):
    """Create a mock InformationPresence object."""
    mock_presence = MagicMock()
    mock_presence.has_vessel_info = has_vessel_info
    mock_presence.has_crew_info = has_crew_info
    mock_presence.has_labor_standards = has_labor_standards
    mock_presence.has_catch_info = has_catch_info
    mock_presence.has_compliance_info = has_compliance_info
    mock_presence.has_species_info = has_species_info
    mock_presence.has_event_details = has_event_details
    mock_presence.has_transshipment = has_transshipment
    mock_presence.has_aquaculture = has_aquaculture
    mock_presence.has_trade_distribution = has_trade_distribution
    mock_presence.has_iuu_classification = has_iuu_classification
    mock_presence.model_dump.return_value = {
        "has_vessel_info": has_vessel_info,
        "has_crew_info": has_crew_info,
        "has_labor_standards": has_labor_standards,
        "has_catch_info": has_catch_info,
        "has_compliance_info": has_compliance_info,
        "has_species_info": has_species_info,
        "has_event_details": has_event_details,
        "has_transshipment": has_transshipment,
        "has_aquaculture": has_aquaculture,
        "has_trade_distribution": has_trade_distribution,
        "has_iuu_classification": has_iuu_classification,
    }
    return mock_presence


class TestIncidentAnalysisModuleInit:
    """Tests for IncidentAnalysisModule initialization."""

    @pytest.mark.unit
    def test_init_creates_all_extractors(self):
        """Test that all DSPy extractors are created."""
        with patch("dspy.ChainOfThought") as mock_cot:
            mock_cot.return_value = MagicMock()
            module = IncidentAnalysisModule()

        # Verify all extractors are created
        assert module.presenceDetector is not None
        assert module.extractAndClassify is not None
        assert module.multiIncidentText is not None
        assert module.multiIncidentClass is not None
        assert module.extract_vessel is not None
        assert module.extract_crew is not None
        assert module.extract_labor_standards is not None
        assert module.extract_catch is not None
        assert module.extract_compliance is not None
        assert module.extract_species is not None
        assert module.extract_event is not None
        assert module.extract_transshipment is not None
        assert module.extract_aquaculture is not None
        assert module.extract_trade_distribution is not None
        assert module.extract_products is not None
        assert module.extract_classification is not None
        assert module.summarize_incident is not None


class TestIncidentAnalysisModuleSingleIncident:
    """Tests for single incident extraction."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_aforward_single_incident_basic(self):
        """Test basic single incident extraction."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.95,
            )
        )

        mock_presence = create_mock_presence(has_vessel_info=True)

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            # Setup presence detector response
            mock_presence_output = MagicMock()
            mock_presence_output.presence = mock_presence

            # Setup other extractor responses
            mock_vessel_output = MagicMock()
            mock_vessel_output.vessel_data = {"vesselName": "Test Vessel"}

            mock_products_output = MagicMock()
            mock_products_output.products = []

            mock_classification_output = MagicMock()
            mock_classification_output.classification = {"iuu_type": "Illegal"}

            mock_summary_output = MagicMock()
            mock_summary_output.summary = "Test incident summary"

            # Configure mock to return different values based on call
            mock_instance.acall.side_effect = [
                mock_presence_output,  # presenceDetector
                mock_vessel_output,  # extract_vessel
                mock_products_output,  # extract_products
                mock_classification_output,  # extract_classification
                mock_summary_output,  # summarize_incident
            ]

            module = IncidentAnalysisModule()
            result = await module.aforward(source)

        assert "sources" in result
        assert result["sources"] == [source]
        assert "parsed_data" in result
        assert "classification" in result
        assert "presence" in result

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_aforward_stores_presence_in_source(self):
        """Test that presence flags are stored in source."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.90,
            )
        )

        mock_presence = create_mock_presence(
            has_vessel_info=True,
            has_species_info=True,
        )

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            mock_presence_output = MagicMock()
            mock_presence_output.presence = mock_presence

            mock_instance.acall.side_effect = [
                mock_presence_output,
                MagicMock(vessel_data=None),
                MagicMock(species_list=[]),
                MagicMock(products=[]),
                MagicMock(classification={}),
                MagicMock(summary="Summary"),
            ]

            module = IncidentAnalysisModule()
            await module.aforward(source)

        # Verify presence was stored
        assert source.information_presence is not None


class TestIncidentAnalysisModuleConditionalExtraction:
    """Tests for conditional extraction based on presence flags."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_extract_conditionally_vessel_present(self):
        """Test that vessel extractor is called when has_vessel_info is True."""
        presence = create_mock_presence(has_vessel_info=True)

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            mock_instance.acall.side_effect = [
                MagicMock(vessel_data={"vesselName": "Test"}),  # vessel
                MagicMock(products=[]),  # products
                MagicMock(classification={}),  # classification
                MagicMock(summary="Summary"),  # summary
            ]

            module = IncidentAnalysisModule()
            result = await module._extract_conditionally("Test text", presence)

        assert result["vesselInformation"] == {"vesselName": "Test"}

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_extract_conditionally_vessel_not_present(self):
        """Test that vessel extractor is skipped when has_vessel_info is False."""
        presence = create_mock_presence(has_vessel_info=False)

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            mock_instance.acall.side_effect = [
                MagicMock(products=[]),  # products (always called)
                MagicMock(classification={}),  # classification (always called)
                MagicMock(summary="Summary"),  # summary (always called)
            ]

            module = IncidentAnalysisModule()
            result = await module._extract_conditionally("Test text", presence)

        assert result["vesselInformation"] is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_extract_conditionally_all_flags_true(self):
        """Test extraction when all presence flags are True."""
        presence = create_mock_presence(
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
        )

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            # All extractors return mock data
            mock_instance.acall.side_effect = [
                MagicMock(vessel_data={"vesselName": "Vessel"}),
                MagicMock(crew_data={"crewCount": 10}),
                MagicMock(labor_standards={"safe": True}),
                MagicMock(catch_data={"location": "Pacific"}),
                MagicMock(compliance_data={"licensed": False}),
                MagicMock(species_list=[{"name": "Tuna"}]),
                MagicMock(event_data={"type": "seizure"}),
                MagicMock(transshipment_data={"occurred": True}),
                MagicMock(aquaculture_data={"farmType": "offshore"}),
                MagicMock(
                    trade_data={},
                    distribution_data={},
                    aggregation_data={},
                    landing_data={},
                ),
                MagicMock(products=[{"type": "fillet"}]),
                MagicMock(classification={"iuu_type": "Illegal"}),
                MagicMock(summary="Full summary"),
            ]

            module = IncidentAnalysisModule()
            result = await module._extract_conditionally("Test text", presence)

        # Verify all fields are populated
        assert result["vesselInformation"] == {"vesselName": "Vessel"}
        assert result["crewInformation"] == {"crewCount": 10}
        assert result["laborStandards"] == {"safe": True}
        assert result["catchInformation"] == {"location": "Pacific"}
        assert result["complianceInformation"] == {"licensed": False}
        assert result["speciesInvolved"] == [{"name": "Tuna"}]
        assert result["eventData"] == {"type": "seizure"}
        assert result["transshipmentInformation"] == {"occurred": True}
        assert result["aquacultureInformation"] == {"farmType": "offshore"}
        assert result["tradeInformation"] == {}
        assert result["productsInvolved"] == [{"type": "fillet"}]
        assert result["classification"] == {"iuu_type": "Illegal"}

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_extract_conditionally_all_flags_false(self):
        """Test extraction when all presence flags are False."""
        presence = create_mock_presence()  # All False by default

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            # Only products, classification, and summary are always called
            mock_instance.acall.side_effect = [
                MagicMock(products=[]),
                MagicMock(classification={}),
                MagicMock(summary="Minimal summary"),
            ]

            module = IncidentAnalysisModule()
            result = await module._extract_conditionally("Test text", presence)

        # Verify optional fields are None or empty
        assert result["vesselInformation"] is None
        assert result["crewInformation"] is None
        assert result["laborStandards"] is None
        assert result["catchInformation"] is None
        assert result["complianceInformation"] is None
        assert result["speciesInvolved"] == []
        assert result["eventData"] is None
        assert result["transshipmentInformation"] is None
        assert result["aquacultureInformation"] is None
        assert result["tradeInformation"] is None
        assert result["chainOfCustody"] is None
        assert result["sanitaryLicenseID"] is None

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_extract_conditionally_with_summary_text(self):
        """Test extraction with custom summary text."""
        presence = create_mock_presence()

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            mock_instance.acall.side_effect = [
                MagicMock(products=[]),
                MagicMock(classification={}),
            ]

            module = IncidentAnalysisModule()
            result = await module._extract_conditionally(
                "Full text", presence, summary_text="Custom summary text"
            )

        # Summary should be the custom text, not generated
        assert result["description"] == "Custom summary text"


class TestIncidentAnalysisModuleRetrieval:
    """Tests for the retrieval path that replaces full-text extraction."""

    @staticmethod
    def _retrieved(text: str, score: float = 0.5):
        """A retrieve_chunks() return value with one scored chunk."""
        return [MagicMock(text=text, score=score)]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_resolve_text_falls_back_to_default_without_store(self):
        """Without a store the full-text fallback passes text through unchanged."""
        with patch("dspy.ChainOfThought"):
            module = IncidentAnalysisModule()
            resolved = await module._resolve_text(
                "vessel", "the whole article", None, None, 5
            )

        assert resolved == "the whole article"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_resolve_text_returns_retrieved_chunks(self):
        """With a store the retrieved chunk text replaces the default text."""
        with patch("dspy.ChainOfThought"), patch(
            "app.dspy_files.modules.retrieve_chunks",
            AsyncMock(return_value=self._retrieved("vessel chunk")),
        ):
            module = IncidentAnalysisModule()
            resolved = await module._resolve_text(
                "vessel", "the whole article", MagicMock(), "src-1", 5
            )

        assert resolved == "vessel chunk"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_each_category_retrieves_its_own_context(self):
        """Every enabled extractor retrieves for its own category, not one shared blob."""
        presence = create_mock_presence(
            has_vessel_info=True, has_crew_info=True, has_species_info=True
        )
        retrieve = AsyncMock(return_value=self._retrieved("chunk"))

        with patch("dspy.ChainOfThought") as mock_cot, patch(
            "app.dspy_files.modules.retrieve_chunks", retrieve
        ):
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock(return_value=MagicMock())
            mock_cot.return_value = mock_instance

            module = IncidentAnalysisModule()
            await module._extract_conditionally(
                "", presence, store=MagicMock(), source_id="src-1"
            )

        categories = [call.args[2] for call in retrieve.await_args_list]
        assert {"vessel", "crew", "species"} <= set(categories)
        # No category is retrieved twice: each extractor gets its own context.
        assert len(categories) == len(set(categories))

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_incident_query_scopes_every_category(self):
        """incident_query is forwarded to retrieval for every category."""
        presence = create_mock_presence(has_vessel_info=True, has_crew_info=True)
        retrieve = AsyncMock(return_value=self._retrieved("chunk"))

        with patch("dspy.ChainOfThought") as mock_cot, patch(
            "app.dspy_files.modules.retrieve_chunks", retrieve
        ):
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock(return_value=MagicMock())
            mock_cot.return_value = mock_instance

            module = IncidentAnalysisModule()
            await module._extract_conditionally(
                "",
                presence,
                store=MagicMock(),
                source_id="src-1",
                incident_query="the seizure of the Ocean Star",
            )

        assert retrieve.await_count > 1
        for call in retrieve.await_args_list:
            assert call.kwargs["extra_query"] == "the seizure of the Ocean Star"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_multi_incident_rag_retrieves_per_category_per_incident(self):
        """Each incident's extractors retrieve their own category-scoped chunks.

        Regression test for the defect where _aforward_rag retrieved 8 chunks
        once per incident and passed that single blob to all 13 extractors as
        plain text, bypassing per-category retrieval entirely. Asserted at the
        _aforward_rag level because the bug lived in the call site, not in
        _extract_conditionally.
        """
        source = create_mock_source(
            article_scope=MagicMock(articleType="Multiple Incidents")
        )
        descriptors = [
            MagicMock(description="Incident A", retrieval_query="the Ocean Star"),
            MagicMock(description="Incident B", retrieval_query="the Blue Marlin"),
        ]
        store = MagicMock()
        store.retrieve = AsyncMock(return_value=self._retrieved("blob"))
        retrieve = AsyncMock(return_value=self._retrieved("chunk"))

        with patch("dspy.ChainOfThought") as mock_cot, patch(
            "app.dspy_files.modules.retrieve_chunks", retrieve
        ), patch(
            "app.dspy_files.modules.segment_incidents",
            AsyncMock(return_value=descriptors),
        ), patch(
            "app.dspy_files.modules.chunk_text", return_value=[]
        ):
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock(return_value=MagicMock())
            mock_cot.return_value = mock_instance

            module = IncidentAnalysisModule()
            await module._aforward_rag(source, store)

        # The old implementation retrieved via store.retrieve once per incident
        # and never reached the per-category helper at all.
        store.retrieve.assert_not_awaited()
        assert retrieve.await_count > len(descriptors)

        # Every incident's query is used, and each is paired with many categories.
        by_incident = {}
        for call in retrieve.await_args_list:
            by_incident.setdefault(call.kwargs["extra_query"], set()).add(call.args[2])

        assert set(by_incident) == {"the Ocean Star", "the Blue Marlin"}
        for categories in by_incident.values():
            assert {"vessel", "crew", "species"} <= categories


class TestIncidentAnalysisModuleMultipleIncidents:
    """Tests for multiple incident extraction."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_aforward_multiple_incidents(self):
        """Test multiple incident extraction with passage splitting."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Multiple Incidents",
                confidence=0.88,
            )
        )

        mock_presence = create_mock_presence()
        mock_passage = MagicMock()
        mock_passage.target_passage = "First incident passage"
        mock_passage.full_context = "Full article context"

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            mock_presence_output = MagicMock()
            mock_presence_output.presence = mock_presence

            mock_split_output = MagicMock()
            mock_split_output.incident_passages = [mock_passage]

            mock_instance.acall.side_effect = [
                mock_presence_output,  # Initial presence detection
                mock_split_output,  # multiIncidentText
                mock_presence_output,  # Passage presence detection
                MagicMock(products=[]),  # products
                MagicMock(classification={}),  # classification
            ]

            module = IncidentAnalysisModule()
            result = await module.aforward(source)

        assert "incidents" in result
        assert len(result["incidents"]) == 1
        assert "presence" in result

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_aforward_multiple_incidents_stores_passages(self):
        """Test that incident passages are stored in source."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Multiple Incidents",
                confidence=0.85,
            )
        )

        mock_presence = create_mock_presence()
        mock_passage1 = MagicMock()
        mock_passage1.target_passage = "Incident 1"
        mock_passage1.full_context = "Full context"

        mock_passage2 = MagicMock()
        mock_passage2.target_passage = "Incident 2"
        mock_passage2.full_context = "Full context"

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            mock_presence_output = MagicMock()
            mock_presence_output.presence = mock_presence

            mock_split_output = MagicMock()
            mock_split_output.incident_passages = [mock_passage1, mock_passage2]

            mock_instance.acall.side_effect = [
                mock_presence_output,  # Initial
                mock_split_output,  # Split
                mock_presence_output,  # Passage 1 presence
                MagicMock(products=[]),
                MagicMock(classification={}),
                mock_presence_output,  # Passage 2 presence
                MagicMock(products=[]),
                MagicMock(classification={}),
            ]

            module = IncidentAnalysisModule()
            await module.aforward(source)

        # Verify passages were stored
        assert source.incident_passages == [mock_passage1, mock_passage2]


class TestIncidentAnalysisModuleMultiIncidentText:
    """Tests for multi-incident text formatting."""

    @pytest.mark.unit
    def test_create_multi_incident_extraction_text(self):
        """Test formatting of multi-incident extraction text."""
        with patch("dspy.ChainOfThought"):
            module = IncidentAnalysisModule()

        target_passage = "The vessel Ocean Raider was seized."
        full_context = "Multiple vessels were caught. The Ocean Raider was one of them."

        result = module._create_multi_incident_extraction_text(
            target_passage, full_context
        )

        # Verify structure
        assert "EXTRACTION INSTRUCTIONS" in result
        assert "TARGET PASSAGE" in result
        assert "FULL CONTEXT" in result
        assert target_passage in result
        assert full_context in result


class TestIncidentAnalysisModuleErrorHandling:
    """Tests for error handling in IncidentAnalysisModule."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_aforward_raises_on_presence_detection_error(self):
        """Test that aforward raises exception on presence detection failure."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.90,
            )
        )

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock(
                side_effect=Exception("Presence detection failed")
            )
            mock_cot.return_value = mock_instance

            module = IncidentAnalysisModule()

            with pytest.raises(Exception, match="Error during extraction"):
                await module.aforward(source)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_aforward_raises_on_extractor_error(self):
        """Test that aforward raises exception on extractor failure."""
        source = create_mock_source(
            article_scope=ArticleScopeClassification(
                articleType="Single Incident",
                confidence=0.90,
            )
        )

        mock_presence = create_mock_presence(has_vessel_info=True)

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            mock_presence_output = MagicMock()
            mock_presence_output.presence = mock_presence

            mock_instance.acall.side_effect = [
                mock_presence_output,
                Exception("Vessel extraction failed"),
            ]

            module = IncidentAnalysisModule()

            with pytest.raises(Exception, match="Error during extraction"):
                await module.aforward(source)


class TestIndustryOverviewModuleInit:
    """Tests for IndustryOverviewModule initialization."""

    @pytest.mark.unit
    def test_init_creates_extractor(self):
        """Test that IndustryOverviewModule creates an extractor."""
        with patch("dspy.ChainOfThought") as mock_cot:
            mock_cot.return_value = MagicMock()
            module = IndustryOverviewModule()

        assert module.extractor is not None


class TestIndustryOverviewModuleExtraction:
    """Tests for IndustryOverviewModule extraction."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_aforward_extracts_overview(self):
        """Test basic industry overview extraction."""
        source = create_mock_source(
            article_text="Industry overview about global fishing trends."
        )

        mock_extracted_data = {"trends": ["declining stocks"], "regions": ["Pacific"]}

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock()
            mock_cot.return_value = mock_instance

            mock_extraction = MagicMock()
            mock_extraction.extracted_data = mock_extracted_data
            mock_instance.acall.return_value = mock_extraction

            module = IndustryOverviewModule()
            result = await module.aforward(source)

        # Verify extraction was called
        mock_instance.acall.assert_called_once_with(source=source)

        # Verify result structure
        assert result["source"] is source
        assert result["extraction"] is mock_extraction
        assert result["parsed_data"] == mock_extracted_data

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_aforward_raises_on_extraction_error(self):
        """Test that aforward raises exception on extraction failure."""
        source = create_mock_source()

        with patch("dspy.ChainOfThought") as mock_cot:
            mock_instance = MagicMock()
            mock_instance.acall = AsyncMock(side_effect=Exception("Extraction failed"))
            mock_cot.return_value = mock_instance

            module = IndustryOverviewModule()

            with pytest.raises(Exception, match="Error during industry overview"):
                await module.aforward(source)


class TestIncidentValidation:
    """Tests for validation logic."""

    @pytest.mark.unit
    def test_validate_extraction_with_none_data(self):
        """Test validation handles None extracted data."""
        with patch("dspy.ChainOfThought"):
            module = IncidentAnalysisModule()

        # Should not raise
        module._validate_extraction(None, "Test text")

    @pytest.mark.unit
    def test_validate_extraction_logs_warnings(self):
        """Test validation logs appropriate warnings."""
        with patch("dspy.ChainOfThought"):
            module = IncidentAnalysisModule()

        mock_data = MagicMock()
        mock_data.speciesInvolved = []
        mock_data.productsInvolved = []
        mock_data.vesselInformation = None
        mock_data.eventData = None

        # Should log warnings but not raise
        with patch("app.dspy_files.modules.logger") as mock_logger:
            module._validate_extraction(mock_data, "fishing vessel caught tuna")
            # Should have warning about species not extracted
            assert mock_logger.warning.called
