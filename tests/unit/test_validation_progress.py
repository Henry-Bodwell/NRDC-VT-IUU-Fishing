from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId

from app.models.incident_data import (
    EventData,
    ExtractedIncidentData,
    LaborStandards,
    Species,
    VesselData,
)
from app.models.incidents import IllegalFishingClassification, IncidentClassification
from app.models.sources import ArticleScopeClassification
from app.service.validation_service import ValidationService


def make_incident():
    return SimpleNamespace(
        id=PydanticObjectId(),
        extracted_information=ExtractedIncidentData(
            vesselInformation=VesselData(vesselName="Test Vessel"),
            eventData=EventData(
                eventDate="2024-01-15",
                eventLocation="Pacific Ocean",
                resolution="Detained",
            ),
            speciesInvolved=[Species(speciesCommonName="Tuna")],
            productsInvolved=[],
            description="Test incident",
        ),
        incident_classification=IncidentClassification(
            iuuClassifications=[
                IllegalFishingClassification(
                    IUUSubType=["Invalid or no permit or license"],
                    IUUTypeReason="No valid license",
                )
            ]
        ),
        verified=False,
    )


def make_session(incident_id: str, reviewed_sections=None):
    return SimpleNamespace(
        source_id=str(PydanticObjectId()),
        validator_id=str(PydanticObjectId()),
        lock_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        reviewed_sections={incident_id: reviewed_sections or []},
    )


def test_progress_requires_explicit_review_for_empty_kde_sections():
    incident = make_incident()
    incident_id = str(incident.id)
    progress = ValidationService.incident_progress(
        incident, make_session(incident_id)
    )

    aquaculture = next(
        row for row in progress["tier_c"]["sections"]
        if row["name"] == "aquacultureInformation"
    )
    assert aquaculture["name"] == "aquacultureInformation"
    assert aquaculture["reviewed"] is False
    assert aquaculture["populated"] is False
    assert aquaculture["population"]["filled"] == 0
    assert aquaculture["population"]["total"] > 0
    assert aquaculture["population"]["unit"] == "fields"
    assert progress["complete"] is False


def test_progress_reports_numeric_field_and_item_population():
    incident = make_incident()
    progress = ValidationService.incident_progress(
        incident, make_session(str(incident.id))
    )

    vessel = next(
        row
        for row in progress["tier_c"]["sections"]
        if row["name"] == "vesselInformation"
    )
    species = next(
        row
        for row in progress["tier_c"]["sections"]
        if row["name"] == "speciesInvolved"
    )

    assert vessel["population"] == {
        "filled": 1,
        "total": len(VesselData.model_fields) - 1,
        "unit": "fields",
    }
    assert species["population"] == {
        "filled": 1,
        "total": None,
        "unit": "items",
    }


def test_progress_accepts_explicit_review_for_every_section():
    incident = make_incident()
    for classification in incident.incident_classification.iuuClassifications:
        classification.verified = True
    incident_id = str(incident.id)
    reviewed = list(incident.extracted_information.model_fields)
    progress = ValidationService.incident_progress(
        incident, make_session(incident_id, reviewed)
    )

    assert progress["tier_b"]["complete"] is True
    assert progress["tier_c"]["complete"] is True
    assert progress["complete"] is True


def test_labor_standards_validated_field_is_normalized_as_reviewed():
    incident = make_incident()
    incident.extracted_information.laborStandards = LaborStandards(validated=True)
    progress = ValidationService.incident_progress(
        incident, make_session(str(incident.id))
    )
    labor = next(
        row for row in progress["tier_c"]["sections"]
        if row["name"] == "laborStandards"
    )
    assert labor["reviewed"] is True


@pytest.mark.asyncio
async def test_single_incident_scope_requires_exactly_one_linked_incident():
    source = SimpleNamespace(
        article_scope=ArticleScopeClassification(
            articleType="Single Incident", confidence=1
        ),
        validated_scope=True,
    )

    progress = await ValidationService.source_progress(source, None, [])

    assert "Single Incident scope requires exactly one incident" in progress[
        "blockers"
    ]


@pytest.mark.asyncio
async def test_multiple_incident_scope_requires_at_least_two_linked_incidents():
    source = SimpleNamespace(
        article_scope=ArticleScopeClassification(
            articleType="Multiple Incidents", confidence=1
        ),
        validated_scope=True,
    )
    incident = make_incident()

    progress = await ValidationService.source_progress(source, None, [incident])

    assert "Multiple Incidents scope requires at least two incidents" in progress[
        "blockers"
    ]
