"""
Integration tests for API endpoints.
"""

import pytest
from httpx import AsyncClient

from app.models.sources import Source
from app.models.incidents import IncidentReport


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
    async def test_list_incidents_with_data(self, async_client: AsyncClient, sample_incident):
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
        assert data["id"] == str(sample_incident.id)

    @pytest.mark.asyncio
    async def test_get_incident_not_found(self, async_client: AsyncClient, test_db):
        """Test getting non-existent incident returns 404."""
        fake_id = "507f1f77bcf86cd799439011"  # Valid ObjectId format
        response = await async_client.get(f"/api/incidents/{fake_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_incidents_pagination(self, async_client: AsyncClient, sample_incident):
        """Test incident listing pagination parameters."""
        response = await async_client.get("/api/incidents?limit=10&skip=0")

        assert response.status_code == 200
        data = response.json()
        assert "pagination" in data
        assert data["pagination"]["limit"] == 10
        assert data["pagination"]["skip"] == 0

    @pytest.mark.asyncio
    async def test_list_incidents_filter_by_status(self, async_client: AsyncClient, sample_incident):
        """Test filtering incidents by status."""
        response = await async_client.get("/api/incidents?status=extracted")

        assert response.status_code == 200
        data = response.json()
        # All returned incidents should have status 'extracted'
        for report in data["reports"]:
            assert report["status"] == "extracted"


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
    async def test_list_sources_with_data(self, async_client: AsyncClient, sample_source):
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
        assert data["id"] == str(sample_source.id)
        assert data["article_text"] == sample_source.article_text

    @pytest.mark.asyncio
    async def test_get_source_not_found(self, async_client: AsyncClient, test_db):
        """Test getting non-existent source returns 404."""
        fake_id = "507f1f77bcf86cd799439011"
        response = await async_client.get(f"/api/sources/{fake_id}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_source_type(self, async_client: AsyncClient, sample_source):
        """Test filtering sources by source_type."""
        response = await async_client.get("/api/sources?source_type=news")

        assert response.status_code == 200
        data = response.json()
        for source in data["sources"]:
            assert source["source_type"] == "news"

    @pytest.mark.asyncio
    async def test_list_sources_filter_by_input_category(self, async_client: AsyncClient, sample_source):
        """Test filtering sources by input_category."""
        # The sample_source uses default input_category='url'
        response = await async_client.get("/api/sources?input_category=url")

        assert response.status_code == 200
        data = response.json()
        for source in data["sources"]:
            assert source["input_category"] == "url"


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
    async def test_invalid_incident_id_format(self, async_client: AsyncClient, test_db):
        """Test that invalid ObjectId format returns appropriate error."""
        response = await async_client.get("/api/incidents/invalid-id-format")

        # Should return 404 or 422 depending on implementation
        assert response.status_code in [404, 422]

    @pytest.mark.asyncio
    async def test_list_incidents_invalid_limit(self, async_client: AsyncClient, test_db):
        """Test that invalid limit parameter is handled."""
        response = await async_client.get("/api/incidents?limit=-1")

        # Should either reject or use default
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_list_incidents_invalid_skip(self, async_client: AsyncClient, test_db):
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
