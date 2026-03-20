from __future__ import annotations
import hashlib
from typing import TYPE_CHECKING, List, Literal
from beanie import Insert, Link, Replace, before_event
from pydantic import Field
from pymongo import TEXT, IndexModel

from app.audit.base import AuditedDocument

# Re-export sub-models so existing imports from app.models.incidents still work
from app.models.iuu_classifications import (  # noqa: F401
    ILLEGAL_FISHING_SUBTYPES,
    UNREPORTED_CATCH_SUBTYPES,
    UNREGULATED_FISHING_SUBTYPES,
    SEAFOOD_FRAUD_SUBTYPES,
    FORCED_LABOR_SUBTYPES,
    SANCTIONS_SUBTYPES,
    AQUACULTURE_SUBTYPES,
    OTHER_SUBTYPES,
    IllegalFishingClassification,
    UnreportedCatchClassification,
    UnregulatedClassification,
    SeafoodFraudClassification,
    ForcedLaborClassification,
    SanctionsClassification,
    IllegalAquacultureClassification,
    OtherIUUClassification,
    IUUClassification,
    IncidentClassification,
)
from app.models.incident_data import (  # noqa: F401
    Species,
    CrewMember,
    EventData,
    VesselData,
    CrewData,
    LaborStandards,
    CatchData,
    ComplianceData,
    AquacultureData,
    TransshipmentData,
    AggregationData,
    LandingData,
    ProductData,
    TradeData,
    DistributionData,
    ExtractedIncidentData,
)
from app.models.overviews import IndustryOverview, IndustryOverviewExtract  # noqa: F401

if TYPE_CHECKING:
    from app.models.sources import Source


class IncidentReport(AuditedDocument):
    """Model to represent an incident report."""

    incident_fingerprint: str | None = Field(
        default=None, description="Unique fingerprint for the incident report"
    )

    sources: List[Link["Source"]] = Field(default_factory=list)
    primary_source: Link["Source"] | None = Field(
        default=None, description="Primary source of the incident report"
    )

    extracted_information: ExtractedIncidentData
    incident_classification: IncidentClassification

    verified: bool = Field(
        default=False,
        description="Whether the incident information has been verified by a human",
    )
    status: Literal["extracted", "from_api", "user_input", "modified"] = Field(
        default="extracted",
        description="Status of the incident. Extracted means the fields were automatically extracted from source. User_input means the report was created by a user. Modified means the report was modified by a user after its creation.",
    )

    class Settings:
        name = "incidents"

        indexes = [
            IndexModel(
                [
                    ("extracted_information.speciesInvolved.speciesCommonName", TEXT),
                    ("extracted_information.speciesInvolved.scientificName", TEXT),
                    ("extracted_information.vesselInformation.vesselName", TEXT),
                    ("extracted_information.vesselInformation.vesselUniqueID", TEXT),
                    ("extracted_information.vesselInformation.vesselFlag", TEXT),
                    ("extracted_information.eventData.eventCountry", TEXT),
                    ("extracted_information.eventData.enforcementCountry", TEXT),
                    ("extracted_information.description", TEXT),
                ]
            )
        ]

    @before_event([Insert, Replace])
    def generate_fingerprint(self):
        """Generate incident fingerprint before saving"""

        if not self.incident_fingerprint:
            eventData = self.extracted_information.eventData
            vesselInfo = self.extracted_information.vesselInformation

            location = (
                eventData.eventLocation
                if eventData and eventData.eventLocation
                else "default_location"
            )
            date = (
                eventData.eventDate
                if eventData and eventData.eventDate
                else "default_date"
            )
            name = (
                vesselInfo.vesselName
                if vesselInfo and vesselInfo.vesselName
                else "default_vessel"
            )

            fingerprint_data = f"{name}_" f"{date}_" f"{location}"
            self.incident_fingerprint = hashlib.sha256(
                fingerprint_data.encode()
            ).hexdigest()

    async def add_source(self, source: "Source", is_primary: bool = False):
        """Helper method to add a source and maintain bidirectional relationship"""
        try:
            # Helper function to get ID from either Link or document object
            def get_id(obj):
                if hasattr(obj, "ref"):
                    return obj.ref.id
                return obj.id

            # If source is a Link, fetch the actual document
            if hasattr(source, "fetch"):
                source_doc = await source.fetch()
            else:
                source_doc = source

            if self.sources is None:
                self.sources = []
            source_ids = [get_id(s) for s in self.sources]
            if source_doc.id not in source_ids:
                self.sources.append(source_doc)

            if is_primary:
                self.primary_source = source_doc

            await self.save()

            incident_ids = (
                [get_id(i) for i in source_doc.incidents]
                if source_doc.incidents
                else []
            )
            if self.id not in incident_ids:
                source_doc.incidents.append(self)
                await source_doc.save()

        except Exception as e:
            raise Exception(f"Failed to add source to incident: {e}")

    async def remove_source(self, source: "Source"):
        """Helper method to remove a source and maintain bidirectional relationship"""
        try:
            # Helper function to get ID from either Link or document object
            def get_id(obj):
                if hasattr(obj, "ref"):
                    return obj.ref.id
                return obj.id

            # If source is a Link, fetch the actual document
            if hasattr(source, "fetch"):
                source_doc = await source.fetch()
            else:
                source_doc = source

            source_id = get_id(source)
            self.sources = [s for s in self.sources if get_id(s) != source_id]

            if self.primary_source and get_id(self.primary_source) == source_id:
                self.primary_source = self.sources[0] if self.sources else None

            if source_doc and source_doc.incidents:
                source_doc.incidents = [
                    i for i in source_doc.incidents if get_id(i) != self.id
                ]
                await source_doc.save()

            await self.save()
        except Exception as e:
            raise Exception(f"Failed to remove source from incident: {e}")

    async def delete(self):
        """Override delete method to handle source removal"""
        try:
            for source in self.sources:
                await self.remove_source(source)

            self.sources = []
            self.primary_source = None
            await super().delete()
        except Exception as e:
            raise Exception(f"Failed to delete incident report: {e}")

    @classmethod
    async def find_potential_duplicates(
        cls, incident_data: "ExtractedIncidentData", threshold: float = 0.8
    ):
        # Could use vessel name, location proximity, date proximity, etc.
        # TODO
        """Find potential duplicate incidents based on similarity"""
        vessel_name = getattr(incident_data.catchSourceInformation, "vesselName", None)
        if vessel_name:
            return await cls.find(
                cls.extracted_information.catchSourceInformation.vesselName
                == vessel_name
            ).to_list()
        return []
