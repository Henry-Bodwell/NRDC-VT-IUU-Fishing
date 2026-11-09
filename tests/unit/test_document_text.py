"""Unit tests for app/rag/document_text.py (document-level embedding text)."""

from types import SimpleNamespace

import pytest

from app.models.incidents import CatchData, EventData, Species, VesselData
from app.rag.document_text import (
    incident_embedding_text,
    incident_iuu_types,
    overview_embedding_text,
    text_hash,
)
from tests.conftest import (
    make_classification,
    make_extracted_data,
    make_overview_extract,
)


def fake_incident(id=None, **data_overrides):
    """Duck-typed incident: the code under test only reads attributes, and a
    real IncidentReport requires an initialised Beanie collection."""
    return SimpleNamespace(
        id=id,
        embedding_text_hash=None,
        extracted_information=make_extracted_data(**data_overrides),
        incident_classification=make_classification(),
    )


def fake_overview(**overrides):
    return SimpleNamespace(
        id=None,
        embedding_text_hash=None,
        extracted_information=make_overview_extract(**overrides),
    )


@pytest.mark.unit
class TestIncidentEmbeddingText:
    def test_includes_labelled_kdes(self):
        incident = fake_incident(
            vesselInformation=VesselData(vesselName="Ocean Star", vesselFlag="Panama"),
            eventData=EventData(
                eventDate="2024-03-02",
                eventLocation="Gulf of Mannar",
                eventCountry="Sri Lanka",
                resolution="Arrested",
            ),
            speciesInvolved=[
                Species(speciesCommonName="Atlantic cod", scientificName="Gadus morhua")
            ],
            description="Trawler arrested for fishing in Sri Lankan waters.",
        )
        text, _ = incident_embedding_text(incident)

        assert text.splitlines()[0] == (
            "Incident: Trawler arrested for fishing in Sri Lankan waters."
        )
        assert "Vessel: Ocean Star" in text
        assert "Flag: Panama" in text
        assert "Date: 2024-03-02" in text
        assert "Location: Gulf of Mannar" in text
        assert "Country: Sri Lanka" in text
        assert "Species: Atlantic cod (Gadus morhua)" in text
        assert "IUU types: Illegal Fishing" in text

    def test_omits_empty_fields(self):
        incident = fake_incident(
            vesselInformation=None,
            eventData=None,
            speciesInvolved=[],
        )
        text, _ = incident_embedding_text(incident)

        assert "Vessel" not in text
        assert "Date" not in text
        assert "Species" not in text
        assert "None" not in text

    def test_location_merges_catch_area_without_duplicates(self):
        incident = fake_incident(
            eventData=EventData(eventLocation="Palk Strait", resolution="x"),
            catchInformation=CatchData(catchArea="palk strait"),
        )
        text, _ = incident_embedding_text(incident)
        assert "Location: Palk Strait\n" in text + "\n"

    def test_hash_is_stable_and_tracks_changes(self):
        first = fake_incident()
        second = fake_incident()
        assert incident_embedding_text(first)[1] == incident_embedding_text(second)[1]

        second.extracted_information.description = "Something else entirely."
        assert incident_embedding_text(first)[1] != incident_embedding_text(second)[1]

    def test_hash_matches_text(self):
        text, digest = incident_embedding_text(fake_incident())
        assert digest == text_hash(text)

    def test_iuu_types(self):
        assert incident_iuu_types(fake_incident()) == ["Illegal Fishing"]


@pytest.mark.unit
class TestOverviewEmbeddingText:
    def test_includes_summary_and_lists(self):
        overview = fake_overview(
            summary="Cod stocks under pressure in the Barents Sea.",
            species=[Species(speciesCommonName="Atlantic cod")],
            countries=["Norway", "Russia", "norway"],
            companies=["Acme Fisheries"],
        )
        text, _ = overview_embedding_text(overview)

        assert text.startswith("Overview: Cod stocks under pressure")
        assert "Species: Atlantic cod" in text
        assert "Countries: Norway, Russia" in text
        assert "Companies: Acme Fisheries" in text
