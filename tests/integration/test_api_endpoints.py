"""
Integration tests for API endpoints.
"""

import pytest
from httpx import AsyncClient

from app.models.sources import Source


class TestIncidentsAPI:
    """Tests for /api/incidents endpoints."""

    @pytest.mark.asyncio
    async def test_list_incidents_empty(self, async_client: AsyncClient):
        """Test listing incidents when none exist."""
        response = await async_client.get("/api/incidents")

        assert response.status_code == 200
        data = response.json()
        assert data["reports"] == []
        assert data["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_incidents_with_data(
        self, async_client: AsyncClient, sample_incident
    ):
        """Test listing incidents when data exists."""
        response = await async_client.get("/api/incidents")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1
        assert len(data["reports"]) >= 1

    @pytest.mark.asyncio
    async def test_get_incident_by_id(self, async_client: AsyncClient, sample_incident):
        """Test getting a specific incident by ID."""
        response = await async_client.get(f"/api/incidents/{sample_incident.id}")

        assert response.status_code == 200
        data = response.json()
        # Handle both 'id' and '_id' field names (Beanie serialization)
        response_id = data.get("id") or data.get("_id")
        assert response_id == str(sample_incident.id)

    @pytest.mark.asyncio
    async def test_get_incident_not_found(self, async_client: AsyncClient, test_db):
        """Test getting non-existent incident returns 404."""
        fake_id = "507f1f77bcf86cd799439011"  # Valid ObjectId format
        response = await async_client.get(f"/api/incidents/{fake_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_incidents_pagination(
        self, async_client: AsyncClient, sample_incident
    ):
        """Test incident listing pagination parameters."""
        response = await async_client.get("/api/incidents?limit=10&skip=0")

        assert response.status_code == 200
        data = response.json()
        assert "pagination" in data
        assert data["pagination"]["limit"] == 10
        assert data["pagination"]["skip"] == 0

    @pytest.mark.asyncio
    async def test_list_incidents_filter_by_status(
        self, async_client: AsyncClient, sample_incident
    ):
        """Test filtering incidents by status."""
        response = await async_client.get("/api/incidents?status=extracted")

        assert response.status_code == 200
        data = response.json()
        # All returned incidents should have status 'extracted'
        for report in data["reports"]:
            assert report["status"] == "extracted"

    @pytest.mark.asyncio
    async def test_search_incidents_matches_vessel_name(
        self, async_client: AsyncClient, sample_incident
    ):
        """Test that search returns incidents whose vessel name contains the term."""
        # sample_incident has vesselName "Test Vessel"
        response = await async_client.get("/api/incidents?search=Vessel")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1
        ids = [r.get("id") or r.get("_id") for r in data["reports"]]
        assert str(sample_incident.id) in ids

    @pytest.mark.asyncio
    async def test_search_incidents_matches_description(
        self, async_client: AsyncClient, sample_incident
    ):
        """Test that search matches against the extracted description field."""
        # sample_incident description: "Test vessel caught fishing illegally..."
        response = await async_client.get("/api/incidents?search=illegally")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_incidents_no_match_returns_empty(
        self, async_client: AsyncClient, sample_incident
    ):
        """Test that an unmatched search term returns no incidents."""
        response = await async_client.get("/api/incidents?search=XYZZY_NOMATCH_12345")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] == 0
        assert data["reports"] == []

    @pytest.mark.asyncio
    async def test_search_incidents_excludes_non_matching(
        self, async_client: AsyncClient, test_db
    ):
        """Test that search only returns incidents containing the search term."""
        from app.models.incidents import (
            IncidentReport,
            ExtractedIncidentData,
            VesselData,
            EventData,
            IncidentClassification,
            IllegalFishingClassification,
            Species,
        )

        matching = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Neptune Explorer"),
                eventData=EventData(
                    eventDate="2024-03-01",
                    eventLocation="Atlantic Ocean",
                    resolution="Vessel detained",
                ),
                speciesInvolved=[Species(speciesCommonName="Cod")],
                productsInvolved=[],
                description="Neptune Explorer seized for illegal trawling.",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUTypeReason="Vessel trawled without a valid permit."
                    )
                ]
            ),
            status="extracted",
        )
        non_matching = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Pacific Star"),
                eventData=EventData(
                    eventDate="2024-04-01",
                    eventLocation="Pacific Ocean",
                    resolution="Fine issued",
                ),
                speciesInvolved=[Species(speciesCommonName="Tuna")],
                productsInvolved=[],
                description="Pacific Star fined for quota violation.",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUTypeReason="Vessel exceeded its annual quota."
                    )
                ]
            ),
            status="extracted",
        )
        await matching.insert()
        await non_matching.insert()

        response = await async_client.get("/api/incidents?search=Neptune")

        assert response.status_code == 200
        data = response.json()
        returned_ids = [r.get("id") or r.get("_id") for r in data["reports"]]
        assert str(matching.id) in returned_ids
        assert str(non_matching.id) not in returned_ids

    @pytest.mark.asyncio
    async def test_search_incidents_combined_with_status_filter(
        self, async_client: AsyncClient, test_db
    ):
        """Test that search composes correctly with status filter."""
        from app.models.incidents import (
            IncidentReport,
            ExtractedIncidentData,
            VesselData,
            EventData,
            IncidentClassification,
            IllegalFishingClassification,
            Species,
        )

        extracted = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Coral Dawn"),
                eventData=EventData(
                    eventDate="2024-05-01",
                    eventLocation="Indian Ocean",
                    resolution="Under investigation",
                ),
                speciesInvolved=[Species(speciesCommonName="Shark")],
                productsInvolved=[],
                description="Coral Dawn investigated for shark finning.",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUTypeReason="Vessel caught prohibited species."
                    )
                ]
            ),
            status="extracted",
        )
        user_input = IncidentReport(
            extracted_information=ExtractedIncidentData(
                vesselInformation=VesselData(vesselName="Coral Reef"),
                eventData=EventData(
                    eventDate="2024-06-01",
                    eventLocation="Red Sea",
                    resolution="Charges pending",
                ),
                speciesInvolved=[Species(speciesCommonName="Grouper")],
                productsInvolved=[],
                description="Coral Reef reported for finning violations.",
            ),
            incident_classification=IncidentClassification(
                iuuClassifications=[
                    IllegalFishingClassification(
                        IUUTypeReason="Vessel finned sharks without authorization."
                    )
                ]
            ),
            status="user_input",
        )
        await extracted.insert()
        await user_input.insert()

        response = await async_client.get(
            "/api/incidents?search=Coral&status=extracted"
        )

        assert response.status_code == 200
        data = response.json()
        returned_ids = [r.get("id") or r.get("_id") for r in data["reports"]]
        assert str(extracted.id) in returned_ids
        assert str(user_input.id) not in returned_ids


class TestSourcesAPI:
    """Tests for /api/sources endpoints."""

    @pytest.mark.asyncio
    async def test_list_sources_empty(self, async_client: AsyncClient, test_db):
        """Test listing sources when none exist."""
        response = await async_client.get("/api/sources")

        assert response.status_code == 200
        data = response.json()
        assert data["sources"] == []
        assert data["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_sources_with_data(
        self, async_client: AsyncClient, sample_source
    ):
        """Test listing sources when data exists."""
        response = await async_client.get("/api/sources")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1
        assert len(data["sources"]) >= 1

    @pytest.mark.asyncio
    async def test_get_source_by_id(self, async_client: AsyncClient, sample_source):
        """Test getting a specific source by ID."""
        response = await async_client.get(f"/api/sources/{sample_source.id}")

        assert response.status_code == 200
        data = response.json()
        # Handle both 'id' and '_id' field names (Beanie serialization)
        response_id = data.get("id") or data.get("_id")
        assert response_id == str(sample_source.id)
        assert data["article_text"] == sample_source.article_text

    @pytest.mark.asyncio
    async def test_get_source_not_found(self, async_client: AsyncClient, test_db):
        """Test getting non-existent source returns 404."""
        fake_id = "507f1f77bcf86cd799439011"
        response = await async_client.get(f"/api/sources/{fake_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_source_type(
        self, async_client: AsyncClient, sample_source
    ):
        """Test filtering sources by source_type."""
        response = await async_client.get("/api/sources?source_type=news")

        assert response.status_code == 200
        data = response.json()
        for source in data["sources"]:
            assert source["source_type"] == "news"

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_input_category(
        self, async_client: AsyncClient, sample_source
    ):
        """Test filtering sources by input_category."""
        # The sample_source uses default input_category='url'
        response = await async_client.get("/api/sources?input_category=url")

        assert response.status_code == 200
        data = response.json()
        for source in data["sources"]:
            assert source["input_category"] == "url"

    @pytest.mark.asyncio
    async def test_search_sources_matches_article_text(
        self, async_client: AsyncClient, sample_source
    ):
        """Test that search returns sources whose article_text contains the term."""
        response = await async_client.get("/api/sources?search=vessel")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1
        ids = [s.get("id") or s.get("_id") for s in data["sources"]]
        assert str(sample_source.id) in ids

    @pytest.mark.asyncio
    async def test_search_sources_matches_publisher(
        self, async_client: AsyncClient, sample_source
    ):
        """Test that search matches against the publisher field."""
        # sample_source publisher is "Test News"
        response = await async_client.get("/api/sources?search=News")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_sources_no_match_returns_empty(
        self, async_client: AsyncClient, sample_source
    ):
        """Test that a search term with no matches returns an empty result set."""
        response = await async_client.get("/api/sources?search=XYZZY_NOMATCH_12345")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] == 0
        assert data["sources"] == []

    @pytest.mark.asyncio
    async def test_search_sources_excludes_non_matching(
        self, async_client: AsyncClient, test_db
    ):
        """Test that search only returns sources containing the search term."""
        matching = Source(
            article_text="The trawler Neptune was seized for unreported salmon catch.",
            article_title="Neptune Seizure",
            publisher="Ocean Watch",
            source_type="news",
            status="extracted",
        )
        non_matching = Source(
            article_text="Government announces new aquaculture subsidy program.",
            article_title="Aquaculture Policy Update",
            publisher="Fisheries Digest",
            source_type="government",
            status="extracted",
        )
        await matching.insert()
        await non_matching.insert()

        response = await async_client.get("/api/sources?search=Neptune")

        assert response.status_code == 200
        data = response.json()
        returned_ids = [s.get("id") or s.get("_id") for s in data["sources"]]
        assert str(matching.id) in returned_ids
        assert str(non_matching.id) not in returned_ids

    @pytest.mark.asyncio
    async def test_search_combined_with_source_type_filter(
        self, async_client: AsyncClient, test_db
    ):
        """Test that search composes correctly with other filters."""
        news_source = Source(
            article_text="Illegal trawling detected off the coast of Iceland.",
            article_title="Iceland Trawling",
            publisher="Fishing Weekly",
            source_type="news",
            status="extracted",
        )
        gov_source = Source(
            article_text="Illegal trawling enforcement report from coast guard.",
            article_title="Coast Guard Report",
            publisher="Ministry of Fisheries",
            source_type="government",
            status="extracted",
        )
        await news_source.insert()
        await gov_source.insert()

        response = await async_client.get(
            "/api/sources?search=trawling&source_type=government"
        )

        assert response.status_code == 200
        data = response.json()
        returned_ids = [s.get("id") or s.get("_id") for s in data["sources"]]
        assert str(gov_source.id) in returned_ids
        assert str(news_source.id) not in returned_ids

    @pytest.mark.asyncio
    async def test_search_absent_returns_all_sources(
        self, async_client: AsyncClient, sample_source
    ):
        """Test that omitting the search param returns all sources unfiltered."""
        response = await async_client.get("/api/sources")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1


class TestOverviewsAPI:
    """Tests for /api/overviews endpoints."""

    @pytest.mark.asyncio
    async def test_list_overviews_empty(self, async_client: AsyncClient, test_db):
        """Test listing overviews when none exist."""
        response = await async_client.get("/api/overviews")

        assert response.status_code == 200
        data = response.json()
        assert data["overviews"] == []
        assert data["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_search_overviews_matches_summary(
        self, async_client: AsyncClient, test_db
    ):
        """Test that search returns overviews whose summary contains the term."""
        from app.models.incidents import IndustryOverview, IndustryOverviewExtract

        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[],
                countries=["NOR", "ISL"],
                companies=[],
                incidents=[],
                summary="Rising levels of unreported herring catch in Nordic waters.",
            )
        )
        await overview.insert()

        response = await async_client.get("/api/overviews?search=herring")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1
        ids = [o.get("id") or o.get("_id") for o in data["overviews"]]
        assert str(overview.id) in ids

    @pytest.mark.asyncio
    async def test_search_overviews_matches_country(
        self, async_client: AsyncClient, test_db
    ):
        """Test that search matches against the countries array."""
        from app.models.incidents import (
            IndustryOverview,
            IndustryOverviewExtract,
            Species,
        )

        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[Species(speciesCommonName="Salmon")],
                countries=["Kamchatka"],
                companies=[],
                incidents=[],
                summary="Overview of salmon poaching incidents.",
            )
        )
        await overview.insert()

        response = await async_client.get("/api/overviews?search=Kamchatka")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_overviews_no_match_returns_empty(
        self, async_client: AsyncClient, test_db
    ):
        """Test that an unmatched search term returns no overviews."""
        from app.models.incidents import IndustryOverview, IndustryOverviewExtract

        overview = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[],
                countries=["AUS"],
                companies=[],
                incidents=[],
                summary="Overview of fishing trends in Australian waters.",
            )
        )
        await overview.insert()

        response = await async_client.get("/api/overviews?search=XYZZY_NOMATCH_12345")

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["total"] == 0
        assert data["overviews"] == []

    @pytest.mark.asyncio
    async def test_search_overviews_excludes_non_matching(
        self, async_client: AsyncClient, test_db
    ):
        """Test that search only returns overviews containing the search term."""
        from app.models.incidents import IndustryOverview, IndustryOverviewExtract

        matching = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[],
                countries=["CHL"],
                companies=[],
                incidents=[],
                summary="Widespread squid poaching reported off Chilean coast.",
            )
        )
        non_matching = IndustryOverview(
            extracted_information=IndustryOverviewExtract(
                species=[],
                countries=["JPN"],
                companies=[],
                incidents=[],
                summary="Annual industry report on Japanese aquaculture.",
            )
        )
        await matching.insert()
        await non_matching.insert()

        response = await async_client.get("/api/overviews?search=squid")

        assert response.status_code == 200
        data = response.json()
        returned_ids = [o.get("id") or o.get("_id") for o in data["overviews"]]
        assert str(matching.id) in returned_ids
        assert str(non_matching.id) not in returned_ids


class TestLogsAPI:
    """Tests for /api/logs endpoints (requires admin auth in real scenarios)."""

    @pytest.mark.asyncio
    async def test_list_logs_empty(self, async_client: AsyncClient, test_db):
        """Test listing audit logs when none exist."""
        # Note: In production, this requires admin authentication
        # For testing, we might need to mock the auth or test without it
        response = await async_client.get("/api/logs")

        # This might return 401 if auth is required
        # Adjust based on actual auth requirements
        assert response.status_code in [200, 401, 403]


class TestTasksAPI:
    """Tests for /api/tasks endpoints."""

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, async_client: AsyncClient, test_db):
        """Test getting a non-existent task."""
        response = await async_client.get("/api/tasks/nonexistent-task-id")

        assert response.status_code == 404


class TestAPIValidation:
    """Tests for API input validation."""

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="API bug: IUU-Fishing-1mi - Invalid ObjectId raises unhandled exception"
    )
    async def test_invalid_incident_id_format(self, async_client: AsyncClient, test_db):
        """Test that invalid ObjectId format returns appropriate error."""
        response = await async_client.get("/api/incidents/invalid-id-format")

        # Should return 404 or 422 depending on implementation
        assert response.status_code in [404, 422]

    @pytest.mark.asyncio
    async def test_list_incidents_invalid_limit(
        self, async_client: AsyncClient, test_db
    ):
        """Test that invalid limit parameter is handled."""
        response = await async_client.get("/api/incidents?limit=-1")

        # Should either reject or use default
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_list_incidents_invalid_skip(
        self, async_client: AsyncClient, test_db
    ):
        """Test that invalid skip parameter is handled."""
        response = await async_client.get("/api/incidents?skip=-1")

        # Should either reject or use default
        assert response.status_code in [200, 422]


class TestCORSAndHeaders:
    """Tests for CORS and response headers."""

    @pytest.mark.asyncio
    async def test_response_content_type(self, async_client: AsyncClient, test_db):
        """Test that API returns JSON content type."""
        response = await async_client.get("/api/incidents")

        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")
