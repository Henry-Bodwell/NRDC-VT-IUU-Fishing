"""
Unit tests for data models.

Note: Tests that instantiate Beanie Document models (Source, IncidentReport,
IndustryOverview) require the test_db fixture for database initialization.
Tests for pure Pydantic models don't need database access.
"""

import pytest
import hashlib
from datetime import datetime

from app.models.sources import Source, ArticleScopeClassification
from app.models.incidents import (
    IncidentReport,
    ExtractedIncidentData,
    VesselData,
    EventData,
    IncidentClassification,
    IllegalFishingClassification,
    IndustryOverview,
    IndustryOverviewExtract,
    Species,
)


class TestPydanticModels:
    """Tests for pure Pydantic models (no database required)."""

    def test_article_scope_classification(self):
        """Test ArticleScopeClassification validation."""
        scope = ArticleScopeClassification(
            articleType="Single Incident",
            confidence=0.95,
        )

        assert scope.articleType == "Single Incident"
        assert scope.confidence == 0.95

    def test_article_scope_invalid_type(self):
        """Test that invalid article types are rejected."""
        with pytest.raises(ValueError):
            ArticleScopeClassification(
                articleType="Invalid Type",
                confidence=0.5,
            )

    def test_vessel_data(self):
        """Test VesselData model."""
        vessel = VesselData(
            vesselName="MV Oceanic",
            vesselIMO="1234567",
            flagState="Liberia",
            vesselType="Fishing Trawler",
        )

        assert vessel.vesselName == "MV Oceanic"
        assert vessel.vesselIMO == "1234567"
        assert vessel.flagState == "Liberia"

    def test_event_data(self):
        """Test EventData model."""
        event = EventData(
            eventDate="2024-06-15",
            eventLocation="South China Sea",
            eventLocationCategory="High Seas",
            enforcementCategory="Maritime Patrol",
        )

        assert event.eventDate == "2024-06-15"
        assert event.eventLocation == "South China Sea"

    def test_illegal_fishing_classification(self):
        """Test IllegalFishingClassification."""
        classification = IllegalFishingClassification(
            subtype="Fishing in closed areas or closed seasons",
        )

        assert classification.IUUType == "Illegal Fishing"
        assert classification.subtype == "Fishing in closed areas or closed seasons"

    def test_incident_classification_with_multiple(self):
        """Test IncidentClassification with multiple IUU types."""
        classification = IncidentClassification(
            iuuClassifications=[
                IllegalFishingClassification(
                    subtype="Invalid or no permit or license",
                ),
                IllegalFishingClassification(
                    subtype="Exceeding catch quotas",
                ),
            ]
        )

        assert len(classification.iuuClassifications) == 2

    def test_extracted_incident_data(self):
        """Test ExtractedIncidentData model."""
        data = ExtractedIncidentData(
            vesselInformation=VesselData(
                vesselName="Test Vessel",
                flagState="Panama",
            ),
            eventData=EventData(
                eventDate="2024-01-15",
                eventLocation="Pacific Ocean",
            ),
        )

        assert data.vesselInformation.vesselName == "Test Vessel"
        assert data.eventData.eventDate == "2024-01-15"

    def test_industry_overview_extract(self):
        """Test IndustryOverviewExtract model."""
        extract = IndustryOverviewExtract(
            species=[Species(speciesCommonName="Tuna")],
            countries=["Japan", "China"],
            companies=["Fishing Co"],
            mainTopics=["Fishing regulations", "Maritime law"],
            keyFindings=["New policies announced", "Enforcement increased"],
            geographicFocus=["Pacific Ocean", "Southeast Asia"],
        )

        assert "Fishing regulations" in extract.mainTopics
        assert len(extract.keyFindings) == 2

    def test_species_model(self):
        """Test Species model."""
        species = Species(
            speciesCommonName="Bluefin Tuna",
            scientificName="Thunnus thynnus",
            aggregateCommonName="Tuna",
        )

        assert species.speciesCommonName == "Bluefin Tuna"
        assert species.scientificName == "Thunnus thynnus"


class TestSourceModel:
    """Tests for the Source Beanie Document model (requires database)."""

    @pytest.mark.asyncio
    async def test_source_hash_generation(self, test_db):
        """Test that article_hash is generated from article_text."""
        text = "This is a test article about illegal fishing."
        source = Source(article_text=text)

        expected_hash = hashlib.sha256(text.encode()).hexdigest()
        assert source.article_hash == expected_hash

    @pytest.mark.asyncio
    async def test_source_hash_changes_with_text(self, test_db):
        """Test that different text produces different hashes."""
        source1 = Source(article_text="Article one about fishing")
        source2 = Source(article_text="Article two about fishing")

        assert source1.article_hash != source2.article_hash

    @pytest.mark.asyncio
    async def test_source_hash_consistent(self, test_db):
        """Test that same text produces same hash."""
        text = "Consistent article text"
        source1 = Source(article_text=text)
        source2 = Source(article_text=text)

        assert source1.article_hash == source2.article_hash

    @pytest.mark.asyncio
    async def test_source_default_values(self, test_db):
        """Test that Source has correct default values."""
        source = Source(article_text="Test article")

        assert source.input_category == "url"
        assert source.source_type == "not specified"
        assert source.status == "extracted"
        assert source.incidents == []
        assert source.overview is None

    @pytest.mark.asyncio
    async def test_source_with_all_fields(self, test_db):
        """Test Source creation with all fields populated."""
        source = Source(
            url="https://example.com/article",
            article_title="Test Title",
            article_text="Test article content",
            author="John Doe",
            publisher="Test News",
            publication_date=datetime(2024, 1, 15),
            input_category="url",
            source_type="news",
            status="extracted",
        )

        assert source.url == "https://example.com/article"
        assert source.article_title == "Test Title"
        assert source.author == "John Doe"
        assert source.publisher == "Test News"
        assert source.source_type == "news"


class TestIncidentReportModel:
    """Tests for the IncidentReport Beanie Document model (requires database)."""

    @pytest.mark.asyncio
    async def test_incident_creation(self, test_db):
        """Test basic IncidentReport creation."""
        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(
                    vesselName="Test Vessel",
                    flagState="Panama",
                ),
                eventData=EventData(
                    eventDate="2024-01-15",
                    eventLocation="Pacific Ocean",
                ),
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        subtype="Fishing in closed areas or closed seasons",
                    )
                ]
            ),
        )

        assert incident.extracted_information.vesselInformation.vesselName == "Test Vessel"
        assert incident.extracted_information.eventData.eventDate == "2024-01-15"

    @pytest.mark.asyncio
    async def test_incident_default_status(self, test_db):
        """Test that IncidentReport has default status."""
        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        subtype="Invalid or no permit or license",
                    )
                ]
            ),
        )

        assert incident.status == "extracted"
        assert incident.verified is False


class TestIndustryOverviewModel:
    """Tests for the IndustryOverview Beanie Document model (requires database)."""

    @pytest.mark.asyncio
    async def test_industry_overview_creation(self, test_db):
        """Test basic IndustryOverview creation."""
        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[Species(speciesCommonName="Tuna")],
                countries=["Japan", "China"],
                companies=["Fishing Co"],
                mainTopics=["Fishing regulations", "Maritime law"],
                keyFindings=["New policies announced", "Enforcement increased"],
                geographicFocus=["Pacific Ocean", "Southeast Asia"],
            )
        )

        assert "Fishing regulations" in overview.extracted_information.mainTopics
        assert len(overview.extracted_information.keyFindings) == 2


class TestModelRelationships:
    """Tests for model relationships (requires database)."""

    @pytest.mark.asyncio
    async def test_source_incident_relationship(self, test_db, sample_source, sample_incident):
        """Test that source and incident are properly linked."""
        # Refresh from database
        source = await Source.get(sample_source.id, fetch_links=True)
        incident = await IncidentReport.get(sample_incident.id, fetch_links=True)

        # Check incident has source linked
        assert len(incident.sources) > 0
        assert incident.primary_source is not None

        # Check source has incident linked
        assert len(source.incidents) > 0

    @pytest.mark.asyncio
    async def test_source_hash_uniqueness(self, test_db):
        """Test that duplicate article_hash raises error on insert."""
        from pymongo.errors import DuplicateKeyError

        text = "This is duplicate content"
        source1 = Source(article_text=text)
        await source1.insert()

        source2 = Source(article_text=text)
        with pytest.raises(DuplicateKeyError):
            await source2.insert()

    @pytest.mark.asyncio
    async def test_incident_add_source(self, test_db):
        """Test adding source to incident."""
        # Create source
        source = Source(
            article_text="Test article for relationship testing",
            source_type="news",
        )
        await source.insert()

        # Create incident
        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Relationship Test Vessel"),
                eventData=EventData(eventDate="2024-03-01"),
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        subtype="Invalid or no permit or license",
                    )
                ]
            ),
        )
        await incident.insert()

        # Add source to incident
        await incident.add_source(source, is_primary=True)

        # Verify relationship
        refreshed_incident = await IncidentReport.get(incident.id, fetch_links=True)
        assert refreshed_incident.primary_source is not None
        assert len(refreshed_incident.sources) == 1

    @pytest.mark.asyncio
    async def test_source_delete_cascades(self, test_db):
        """Test that deleting source with single incident deletes incident."""
        # Create source
        source = Source(
            article_text="Article for cascade delete test",
            source_type="news",
        )
        await source.insert()

        # Create incident linked only to this source
        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Cascade Test Vessel"),
                eventData=EventData(eventDate="2024-04-01"),
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        subtype="Invalid or no permit or license",
                    )
                ]
            ),
        )
        await incident.insert()
        await incident.add_source(source, is_primary=True)

        incident_id = incident.id

        # Delete source
        await source.delete()

        # Verify incident was also deleted
        deleted_incident = await IncidentReport.get(incident_id)
        assert deleted_incident is None
