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
    ProductData,
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
        """Test VesselData model with correct field names."""
        vessel = VesselData(
            vesselName="MV Oceanic",
            vesselUniqueID="IMO1234567",
            vesselFlag="Liberia",
            mmsiNumber="123456789",
        )

        assert vessel.vesselName == "MV Oceanic"
        assert vessel.vesselUniqueID == "IMO1234567"
        assert vessel.vesselFlag == "Liberia"
        assert vessel.verified is False  # default

    def test_event_data(self):
        """Test EventData model - resolution is required."""
        event = EventData(
            eventDate="2024-06-15",
            eventLocation="South China Sea",
            eventLocationCategory="High Seas",
            enforcementCategory="Maritime Patrol",
            resolution="Vessel detained and crew fined",
        )

        assert event.eventDate == "2024-06-15"
        assert event.eventLocation == "South China Sea"
        assert event.resolution == "Vessel detained and crew fined"

    def test_event_data_requires_resolution(self):
        """Test that EventData requires resolution field."""
        with pytest.raises(ValueError):
            EventData(
                eventDate="2024-06-15",
                eventLocation="South China Sea",
                # missing resolution - should fail
            )

    def test_illegal_fishing_classification(self):
        """Test IllegalFishingClassification with correct field names."""
        classification = IllegalFishingClassification(
            IUUSubType=["Fishing in closed areas or closed seasons"],
            IUUTypeReason="Vessel was found fishing in a protected marine area during closed season.",
        )

        assert classification.IUUType == "Illegal Fishing"
        assert "Fishing in closed areas or closed seasons" in classification.IUUSubType
        assert "protected marine area" in classification.IUUTypeReason

    def test_illegal_fishing_requires_reason(self):
        """Test that IllegalFishingClassification requires IUUTypeReason."""
        with pytest.raises(ValueError):
            IllegalFishingClassification(
                IUUSubType=["Exceeding catch quotas"],
                # missing IUUTypeReason - should fail
            )

    def test_incident_classification_with_multiple(self):
        """Test IncidentClassification with multiple IUU types."""
        classification = IncidentClassification(
            iuuClassifications=[
                IllegalFishingClassification(
                    IUUSubType=["Invalid or no permit or license"],
                    IUUTypeReason="Vessel operated without valid fishing license.",
                ),
                IllegalFishingClassification(
                    IUUSubType=["Exceeding catch quotas"],
                    IUUTypeReason="Catch exceeded allocated quota by 50%.",
                ),
            ]
        )

        assert len(classification.iuuClassifications) == 2

    def test_extracted_incident_data(self):
        """Test ExtractedIncidentData model."""
        data = ExtractedIncidentData(
            vesselInformation=VesselData(
                vesselName="Test Vessel",
                vesselFlag="Panama",
            ),
            eventData=EventData(
                eventDate="2024-01-15",
                eventLocation="Pacific Ocean",
                resolution="Vessel seized",
            ),
            speciesInvolved=[Species(speciesCommonName="Tuna")],
            productsInvolved=[ProductData(productType="Frozen fish")],
            description="Test vessel caught fishing illegally in protected waters.",
        )

        assert data.vesselInformation.vesselName == "Test Vessel"
        assert data.eventData.eventDate == "2024-01-15"
        assert data.eventData.resolution == "Vessel seized"
        assert len(data.speciesInvolved) == 1
        assert (
            data.description
            == "Test vessel caught fishing illegally in protected waters."
        )

    def test_industry_overview_extract(self):
        """Test IndustryOverviewExtract model with correct fields."""
        extract = IndustryOverviewExtract(
            species=[Species(speciesCommonName="Tuna")],
            countries=["Japan", "China"],
            companies=["Fishing Co", "Ocean Corp"],
            incidents=[
                ExtractedIncidentData(
                    speciesInvolved=[Species(speciesCommonName="Tuna")],
                    productsInvolved=[],
                    description="Incident in the Pacific region.",
                )
            ],
            summary="Overview of fishing industry trends in the Pacific region.",
        )

        assert len(extract.species) == 1
        assert "Japan" in extract.countries
        assert "Fishing Co" in extract.companies
        assert "Pacific region" in extract.summary

    def test_species_model(self):
        """Test Species model."""
        species = Species(
            speciesCommonName="Bluefin Tuna",
            scientificName="Thunnus thynnus",
            aggregateCommonName="Tuna",
        )

        assert species.speciesCommonName == "Bluefin Tuna"
        assert species.scientificName == "Thunnus thynnus"
        assert species.verified is False  # default


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

    @pytest.mark.asyncio
    async def test_source_persist_and_retrieve(self, test_db):
        """Test that Source can be saved and retrieved from database."""
        source = Source(
            article_text="Test article for persistence",
            source_type="news",
        )
        await source.insert()

        # Retrieve from database
        retrieved = await Source.get(source.id)
        assert retrieved is not None
        assert retrieved.article_text == "Test article for persistence"
        assert retrieved.article_hash == source.article_hash


class TestIncidentReportModel:
    """Tests for the IncidentReport Beanie Document model (requires database)."""

    @pytest.mark.asyncio
    async def test_incident_creation(self, test_db):
        """Test basic IncidentReport creation."""
        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(
                    vesselName="Test Vessel",
                    vesselFlag="Panama",
                ),
                eventData=EventData(
                    eventDate="2024-01-15",
                    eventLocation="Pacific Ocean",
                    resolution="Vessel detained",
                ),
                speciesInvolved=[Species(speciesCommonName="Tuna")],
                productsInvolved=[],
                description="Test vessel caught fishing illegally.",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUSubType=["Fishing in closed areas or closed seasons"],
                        IUUTypeReason="Caught fishing in marine protected area.",
                    )
                ]
            ),
        )

        assert (
            incident.extracted_information.vesselInformation.vesselName == "Test Vessel"
        )
        assert incident.extracted_information.eventData.eventDate == "2024-01-15"

    @pytest.mark.asyncio
    async def test_incident_default_status(self, test_db):
        """Test that IncidentReport has default status."""
        incident = IncidentReport(
            extracted_information=ExtractedIncidentData(
                eventData=EventData(resolution="Unknown"),
                speciesInvolved=[],
                productsInvolved=[],
                description="Unknown incident.",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUSubType=["Invalid or no permit or license"],
                        IUUTypeReason="Operated without valid license.",
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
                incidents=[
                    ExtractedIncidentData(
                        speciesInvolved=[Species(speciesCommonName="Tuna")],
                        productsInvolved=[],
                        description="Industry incident mentioned in report.",
                    )
                ],
                summary="Industry trends report.",
            )
        )

        assert len(overview.extracted_information.species) == 1
        assert "Japan" in overview.extracted_information.countries


class TestModelRelationships:
    """Tests for model relationships (requires database)."""

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
                eventData=EventData(
                    eventDate="2024-03-01",
                    resolution="Under investigation",
                ),
                speciesInvolved=[],
                productsInvolved=[],
                description="Testing source-incident relationship.",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUSubType=["Invalid or no permit or license"],
                        IUUTypeReason="No valid fishing permit found.",
                    )
                ]
            ),
        )
        await incident.insert()

        # Add source to incident
        await incident.add_source(source, is_primary=True)

        # Verify relationship - refresh incident from DB
        refreshed_incident = await IncidentReport.get(incident.id)
        assert refreshed_incident is not None
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
                eventData=EventData(
                    eventDate="2024-04-01",
                    resolution="Charges pending",
                ),
                speciesInvolved=[],
                productsInvolved=[],
                description="Testing cascade delete behavior.",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUSubType=["Invalid or no permit or license"],
                        IUUTypeReason="License expired.",
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
