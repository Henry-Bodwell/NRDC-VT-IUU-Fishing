"""
Pytest configuration and fixtures for IUU-Fishing tests.
"""

import os
import pytest
from typing import AsyncGenerator, Generator
from unittest.mock import patch, MagicMock

# Load environment variables from .env file
from dotenv import load_dotenv

load_dotenv()

# Set test environment variables before importing app modules
os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-for-testing")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

# Get MongoDB password from environment
MONGO_ROOT_PASSWORD = os.getenv("MONGO_ROOT_PASSWORD", "devpassword123")
# Use port 27018 for local testing (mapped from docker-compose.override.yml)
TEST_MONGO_URI = f"mongodb://admin:{MONGO_ROOT_PASSWORD}@localhost:27018/iuuIncidents_test?authSource=admin"
os.environ["MONGO_URI"] = TEST_MONGO_URI

from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.models.sources import Source
from app.models.incidents import (
    IncidentReport,
    IndustryOverview,
    Species,
    ExtractedIncidentData,
    VesselData,
    EventData,
    IncidentClassification,
    IllegalFishingClassification,
    IndustryOverviewExtract,
)
from app.models.users import User
from app.models.task import TaskStatus
from app.audit.models import AuditLog
from app.dspy_files.news_analysis import PipelineOutput, PipelineResult


# ---------------------------------------------------------------------------
# Factories -- lightweight builders that reduce boilerplate across tests.
# Call with keyword overrides; defaults produce valid, minimal objects.
# ---------------------------------------------------------------------------

_source_counter = 0


def make_source(**overrides) -> Source:
    """Build a Source with sensible defaults. Not yet inserted into the DB."""
    global _source_counter
    _source_counter += 1
    defaults = dict(
        article_text=f"Test article text #{_source_counter}",
        source_type="news",
        status="extracted",
    )
    defaults.update(overrides)
    return Source(**defaults)


def make_extracted_data(**overrides) -> ExtractedIncidentData:
    """Build minimal ExtractedIncidentData."""
    defaults = dict(
        vesselInformation=VesselData(vesselName="Factory Vessel"),
        eventData=EventData(
            eventDate="2024-01-15",
            eventLocation="Pacific Ocean",
            resolution="Detained",
        ),
        speciesInvolved=[Species(speciesCommonName="Tuna")],
        productsInvolved=[],
        description="Factory-generated incident description.",
    )
    defaults.update(overrides)
    return ExtractedIncidentData(**defaults)


def make_classification(**overrides) -> IncidentClassification:
    """Build minimal IncidentClassification."""
    defaults = dict(
        iuuClassifications=[
            IllegalFishingClassification(
                IUUSubType=["Invalid or no permit or license"],
                IUUTypeReason="No valid license.",
            )
        ],
    )
    defaults.update(overrides)
    return IncidentClassification(**defaults)


def make_incident(**overrides) -> IncidentReport:
    """Build an IncidentReport with sensible defaults. Not yet inserted."""
    defaults = dict(
        extracted_information=make_extracted_data(),
        incident_classification=make_classification(),
        status="extracted",
    )
    defaults.update(overrides)
    return IncidentReport(**defaults)


def make_overview_extract(**overrides) -> IndustryOverviewExtract:
    """Build minimal IndustryOverviewExtract."""
    defaults = dict(
        species=[],
        countries=[],
        companies=[],
        incidents=[],
        summary="Factory overview summary.",
    )
    defaults.update(overrides)
    return IndustryOverviewExtract(**defaults)


def make_overview(**overrides) -> IndustryOverview:
    """Build an IndustryOverview with sensible defaults. Not yet inserted."""
    defaults = dict(
        extracted_information=make_overview_extract(),
    )
    defaults.update(overrides)
    return IndustryOverview(**defaults)


def make_pipeline_output(**overrides) -> PipelineOutput:
    """Build a PipelineOutput with sensible defaults."""
    defaults = dict(
        source=make_source(),
        status=PipelineResult.SUCCESS,
        incidents=[],
        industry_overview=None,
    )
    defaults.update(overrides)
    return PipelineOutput(**defaults)


# Test database name
TEST_DB_NAME = "iuuIncidents_test"


@pytest.fixture(scope="function")
async def test_db() -> AsyncGenerator[None, None]:
    """
    Initialize test database before each test and clean up after.

    This fixture:
    1. Creates MongoDB client
    2. Initializes Beanie with test database
    3. Yields control to the test
    4. Drops all collections and closes client after the test
    """
    client = AsyncIOMotorClient(TEST_MONGO_URI)
    db = client[TEST_DB_NAME]

    # Initialize Beanie with all document models
    await init_beanie(
        database=db,
        document_models=[
            Source,
            IncidentReport,
            IndustryOverview,
            User,
            TaskStatus,
            AuditLog,
        ],
    )

    yield

    # Clean up: drop all collections after each test
    for collection_name in await db.list_collection_names():
        await db.drop_collection(collection_name)

    client.close()


@pytest.fixture
async def async_client(test_db) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for testing API endpoints.

    Uses ASGI transport to test the FastAPI app directly without
    starting a server.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def sync_client(test_db) -> Generator[TestClient, None, None]:
    """
    Create a synchronous test client for simpler tests.
    """
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def sample_source(test_db) -> Source:
    """Create and return a sample Source for testing."""
    source = make_source(
        url="https://example.com/test-article",
        article_text="This is a test article about illegal fishing. A vessel named Test Vessel was caught fishing illegally in protected waters on January 15, 2024.",
        article_title="Test Illegal Fishing Article",
        author="Test Author",
        publisher="Test News",
    )
    await source.insert()
    return source


@pytest.fixture
async def sample_incident(test_db, sample_source: Source) -> IncidentReport:
    """Create and return a sample IncidentReport for testing."""
    incident = make_incident(
        extracted_information=make_extracted_data(
            vesselInformation=VesselData(
                vesselName="Test Vessel",
                vesselFlag="Unknown",
            ),
            eventData=EventData(
                eventDate="2024-01-15",
                eventLocation="Protected Waters",
                resolution="Under investigation",
            ),
            description="Test vessel caught fishing illegally in protected waters.",
        ),
    )
    await incident.insert()

    # Link source to incident
    await incident.add_source(sample_source, is_primary=True)

    return incident


@pytest.fixture
async def sample_user(test_db) -> User:
    """Create and return a sample User for testing."""
    user = User(
        email="test@example.com",
        name="Test User",
        hashedPassword="not-a-real-hash",
        role="user",
        is_active=True,
    )
    await user.insert()
    return user


@pytest.fixture
async def admin_user(test_db) -> User:
    """Create and return an admin User for testing."""
    user = User(
        email="admin@example.com",
        name="Admin User",
        hashedPassword="not-a-real-hash",
        role="admin",
        is_active=True,
    )
    await user.insert()
    return user


@pytest.fixture
def mock_dspy():
    """
    Mock DSPy to avoid actual LLM calls during testing.

    Returns a context manager that patches DSPy modules.
    """
    with patch("dspy.ChainOfThought") as mock_cot:
        mock_instance = MagicMock()
        mock_cot.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_openai():
    """Mock OpenAI API calls."""
    with patch("openai.ChatCompletion.create") as mock_create:
        mock_create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Mocked response"))]
        )
        yield mock_create
