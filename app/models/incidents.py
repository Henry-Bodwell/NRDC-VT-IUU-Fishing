from __future__ import annotations
import hashlib
from typing import TYPE_CHECKING, List, Literal
from beanie import Document, Insert, Link, Replace, before_event
from bson import ObjectId
from pydantic import BaseModel, Field
from app.models.logs import LogMixin

if TYPE_CHECKING:
    from app.models.articles import Source


# Pydantic models
class Species(BaseModel):
    """Model to represent a single species involved in an incident."""

    commonName: str = Field(
        ..., description="The common name of the species (e.g., 'Bluefin Tuna')."
    )
    scientificName: str | None = Field(
        description="The scientific name of the species (e.g., 'Thunnus thynnus')."
    )
    ASFISCode: str | None = Field(
        default=None, description="ASFIS 3-Aplha code of the species, if available."
    )
    productType: str | None = Field(
        default=None,
        description="Form of the product (e.g., 'Fins', 'Fillets', 'Whole'), if available.",
    )
    liveWeight: str | None = Field(
        default=None,
        description="Weight of the species when alive, if specified (e.g., '100 kg'), if available.",
    )


class CrewMember(BaseModel):
    """Model to represent a crew member involved in an incident."""

    name: str = Field(..., description="Name of the crew member.")
    nationality: str | None = Field(
        default=None, description="Nationality of the crew member, if available."
    )
    role: str | None = Field(
        default=None,
        description="Role of the crew member on the vessel (e.g., 'Captain', 'Deckhand').",
    )
    age: int | None = Field(
        default=None, description="Age of the crew member, if available."
    )
    tripStartDate: str | None = Field(
        default=None,
        description="Start date of the trip the crew member was involved in, if available.",
    )
    tripEndDate: str | None = Field(
        default=None,
        description="End date of the trip the crew member was involved in, if available.",
    )


class IUUClassification(BaseModel):
    IUUType: Literal[
        "Illegal Fishing",
        "Illegal Fishing Associated Activities",
        "Unreported Catch",
        "Unreported Catch Associated Activities" "Unregulated Actors",
        "Unregulated Areas or Stocks",
        "Seafood Fraud or Mislabeling",
        "Forced Labor or Labor Abuse",
        "Circumventing Prohibitions or Sanctions",
        "Illegal Aquacultural Practices",
        "Other",
    ] = Field(...)

    IUUSubType: List[str] | None = Field(
        default=None,
        description="""The specific subcategory based on IUUType:
        - Illegal Fishing: 'Exceeding catch quotas', 'Keeping undersized fish', 'Catching unauthorized or prohibited species', 'Prohibited fishing gear', 'Fishing in closed areas or closed seasons'
        - Illegal Fishing Associated Activities: 'Invalid permit','Obscuring vessel identity', 'Unauthorized transhipment', 'falsifying documents, excepting fish/transshipment license', 'Objstructing inspectors', 'illegal bycatch practices'
        - Unreported Catch: 'Un/underreported catch weight', 'Un/underreported discards/bycatch', 'Misreported catch species', 'Misreported location', 'Misreported gear'
        - Unreported Catch Associated Activities: 'Unreported transshipment activities'
        - Unregulated Actors: 'Stateless vessel', 'Fishing under flag not party to RFMO' 
        - Unregulated Areas or Stocks: 'Operating for stock or in places to avoid international regulation'
        - Seafood Fraud of Mislabeling: 'Species', 'Production information', 'Processing information'
        - Forced Labor or Labor Abuse: 'Wage/Pay', 'Excessive overtime', 'Restriction of movement', 'Abusive living conditions', 'Abusive working conditions', 'Violence', 'Intimidation', 'ID Rentention', 'Deception', 'Isolation', 'Abuse of Vulnerability'
        - Circumventing Prohibitions or Sanctions: 'Sanctions', 'Prohibitions'
        """,
    )

    IUUTypeReason: str = Field(
        ...,
        description="Reason for the IUU incident, e.g., overfishing, habitat destruction, if other please specify what the IUU type should be and why.",
    )


class EventData(BaseModel):
    """Structured information about the primary event of an IUU incident. ie the event that triggered the article."""

    eventCategory: str = Field(
        ...,
        description="Categorize the primary event (e.g., 'Seizure', 'Arrest', 'Investigation Initiated', 'Fine Issued').",
    )
    eventDate: str | None = Field(
        default=None, description="Date of the primary event (e.g., '2023-10-01')."
    )
    eventLocation: str = Field(
        ...,
        description="Where did the primary event occur? (e.g., 'Pacific Ocean', 'Port of XYZ').",
    )
    resolution: str = Field(
        ...,
        description="What was the outcome or resolution, if mentioned? (e.g., 'Vessel Detained', 'Crew Fined $10,000', 'Charges Dropped').",
    )


class CatchSourceData(BaseModel):
    """The structured information extracted from an article about catch and source of an incident."""

    # Who
    vesselName: str | None = Field(
        default=None, description="Name of the vessel involved"
    )
    vesselUniqueID: str | None = Field(
        default=None, description="ID of the vessel involved"
    )
    vesselFlag: str | None = Field(
        default=None, description="Flag state of the vessel involved"
    )
    internationalRadioCallSign: str | None = Field(
        default=None, description="Call Sign of the vessel involved, if available"
    )
    rmfoVesselNumber: str | None = Field(
        default=None,
        description="Regional Fisheries Management Organization (RFMO) vessel number, if available",
    )
    satelitteVesselTrackingAuthority: str | None = Field(
        default=None,
        description="Authority responsible for satellite tracking of the vessel, if available",
    )
    publicVesselRegistryLink: str | None = Field(
        default=None, description="Link to the public vessel registry, if available"
    )
    vesselCaptain: str | None = Field(
        default=None, description="Name of the vessel captain, if available"
    )
    vesselOwner: str | None = Field(
        default=None, description="Name of the vessel owner, if available"
    )
    beneficialOwner: str | None = Field(
        default=None,
        description="Name of the beneficial owner of the vessel, if available",
    )
    recruitmentAgency: str | None = Field(
        default=None, description="Recruitment agency for the crew, if available"
    )
    recruitmentChannel: str | None = Field(
        default=None,
        description="Channel through which the crew was recruited, if available",
    )
    tradeUnionWorkersOrganization: str | None = Field(
        default=None, description="Trade union or workers' organization, if available"
    )
    migrantWorkers: bool | None = Field(
        default=None,
        description="Whether migrant workers were involved in the incident, if available",
    )
    migrantWorkersDetails: str | None = Field(
        default=None, description="% of crew migrant workers make up, if available"
    )

    genderOfWorkers: str | None = Field(
        default=None, description="gender make up of crew involved, if available"
    )
    crewList: List[CrewMember] | None = Field(
        default=None,
        description="List of crew members involved in the incident, if available",
    )
    fisheryImporvementProject: str | None = Field(
        default=None,
        description="Fishery improvement project associated with the incident, if available",
    )
    # When
    catchDate: str | None = Field(
        default=None, description="Date of the catch, if available"
    )
    vesselTripDates: str | None = Field(
        default=None, description="Dates of the vessel trip, if available"
    )
    timeAtSea: str | None = Field(
        default=None, description="Time spent at sea during the incident, if available"
    )
    # Where
    catchArea: str | None = Field(
        default=None,
        description="Country of Harvest, or EEZ where the catch was made or High seas0, if available",
    )
    authoristionToFish: str | None = Field(
        default=None,
        description="Unique number associated with a regulatory document, from the relevant authority, granting permission for wild-capture of seafood by a fisher or fishing vessel, if available",
    )
    validLicense: bool | None = Field(
        default=None,
        description="Whether the vessel had a valid fishing license, if available",
    )
    licensedDateRange: str | None = Field(
        default=None,
        description="Date range during which the vessel was licensed to fish, if available",
    )
    licensedFishingArea: str | None = Field(
        default=None, description="Licensed fishing area, if available"
    )
    coastalZoneEntryAndExit: str | None = Field(
        default=None,
        description="Coastal zone entry and exit information, if available",
    )
    availabilityOfCatchCoordinates: str | None = Field(
        default=None, description="Catch coordinates, if available"
    )
    AisVmsCoverageRate: str | None = Field(
        default=None, description="AIS/VMS tracking coverage rate, if available"
    )

    # How
    fishingMethod: str | None = Field(
        default=None, description="Method of fishing used in the incident, if available"
    )
    productionMethod: str | None = Field(
        default=None,
        description="Method of production used in the incident, if available",
    )
    harvestCertification: str | None = Field(
        default=None,
        description="Whether harvest certification was obtained, if available",
    )
    partyToUNFSA: bool | None = Field(
        default=None,
        description="Whether the vessel is a party to the United Nations Fish Stocks Agreement (UNFSA), if available",
    )
    cardedUnderEUIUURegulation: bool | None = Field(
        default=None,
        description="Whether the vessel is carded under the EU IUU Regulation, if available",
    )
    inNOAABinannualReport: bool | None = Field(
        default=None,
        description="Whether the vessel is in the NOAA annual report, if available",
    )
    hasHumanWelfarePolicy: bool | None = Field(
        default=None,
        description="Whether the vessel has a human welfare policy, if available",
    )
    humanWelfareStandards: str | None = Field(
        default=None,
        description="Human welfare standards followed by the vessel, if available",
    )
    hasGrievanceMechanism: bool | None = Field(
        default=None,
        description="Whether a grievance mechanism is in place, if available",
    )
    grievanceMechanism: str | None = Field(
        default=None, description="Grievance mechanism in place, if available"
    )
    safetyInspection: bool | None = Field(
        default=None,
        description="Whether a safety inspection was conducted, if available",
    )
    thirdPartyInspection: bool | None = Field(
        default=None,
        description="Whether third-party inspection was conducted, if available",
    )
    inspectionDetails: str | None = Field(
        default=None, description="Details on the inspection, if available"
    )
    healthSafetyRecords: str | None = Field(
        default=None, description="Health and safety records, if available"
    )
    workContracts: bool | None = Field(
        default=None, description="Whether work contracts were provided, if available"
    )
    hasWifi: bool | None = Field(
        default=None, description="Whether the vessel has Wi-Fi access, if available"
    )


class AquacultureData(BaseModel):
    """Model to represent aquaculture data in an IUU incident."""

    farmName: str | None = Field(
        default=None, description="Name of the aquaculture farm, if available"
    )
    farmUniqueID: str | None = Field(
        default=None, description="Unique ID of the aquaculture farm, if available"
    )
    farmLocation: str | None = Field(
        default=None, description="Location of the aquaculture farm, if available"
    )
    fingerlingHarvestDate: str | None = Field(
        default=None,
        description="Date on which fingerlngs were transferred to the grow out farm/pond, if available",
    )
    harvestDate: str | None = Field(
        default=None, description="Date the seafood was harvested, if available"
    )
    farmCounry: str | None = Field(
        default=None, description="Country farm resides in, if available"
    )
    proteinSource: str | None = Field(
        default=None,
        description="Source(s) of protein in formulation of feed used (e.g. soy, insects, wild caught fish byproduct, other, etc), if available",
    )
    farmingMethod: str | None = Field(
        default=None, description="Method of farming, if available."
    )
    stockingQuantity: str | None = Field(
        default=None,
        description="Verifiable number of animals stocked in the production unit, if available.",
    )


class TransshipmentData(BaseModel):
    """Model to represent transshipment data in an IUU incident."""

    vesselName: str | None = Field(
        default=None, description="Name of the transshipment vessel, if available"
    )
    vesselUniqueID: str | None = Field(
        default=None, description="Unique ID of the transshipment vessel, if available"
    )
    vesselFlag: str | None = Field(
        default=None, description="Flag state of the transshipment vessel, if available"
    )
    vesselRegistration: str | None = Field(
        default=None,
        description="Registration of the transshipment vessel, if available",
    )
    transshipmentDeclaration: bool | None = Field(
        default=None,
        description="Whether a transshipment declaration was made, if available",
    )
    transshipmentAuthorization: bool | None = Field(
        default=None, description="Whether transshipment was authorized, if available"
    )
    IMONumber: str | None = Field(
        default=None,
        description="International Maritime Organization (IMO) number of the transshipment vessel, if available",
    )
    vesselMasterInformation: str | None = Field(
        default=None, description="Information about the vessel master, if available"
    )
    datesOfTransshipment: str | None = Field(
        default=None, description="Dates of transshipment, if available"
    )
    locationOfTransshipment: str | None = Field(
        default=None, description="Location of transshipment, if available"
    )


class AggregationData(BaseModel):
    """Model to represent aggregation data in an IUU incident."""

    aggregatorName: str | None = Field(
        default=None,
        description="Name of the aggregator involved in the incident, if available",
    )
    aggregatorID: str | None = Field(
        default=None,
        description="ID of the aggregator involved in the incident, if available",
    )
    aggregatorLicense: str | None = Field(
        default=None, description="License of aggregator if available"
    )


class LandingData(BaseModel):
    """Model to represent landing data in an IUU incident."""

    authorization: str | None = Field(
        default=None, description="Authorization for landing, if available"
    )
    portEntryRequest: str | None = Field(
        default=None, description="Port entry request, if available"
    )
    datesOfLanding: str | None = Field(
        default=None, description="Dates of landing, if available"
    )
    portOfLanding: str | None = Field(
        default=None, description="Port of landing, if available"
    )
    partyToPMSA: bool | None = Field(
        default=None,
        description="Whether the vessel is a party to the Port State Measures Agreement (PMSA), if available",
    )


class ProductData(BaseModel):
    """Model to represent products in an IUU incident."""

    productType: str | None = Field(
        default=None, description="Type of product processed, if available"
    )
    species: List[Species] | None = Field(
        default=None,
        description="List of species involved in the product, if available",
    )
    HSCode: str | None = Field(
        default=None,
        description="Harmonized System (HS) code of the product, if available",
    )
    SKU: str | None = Field(
        default=None,
        description="Stock Keeping Unit (SKU) of the product, if available",
    )
    processedWeight: str | None = Field(
        default=None, description="Weight of the processed product, if available"
    )
    processingLocation: str | None = Field(
        default=None, description="Location(s) of processing, if available"
    )
    additivesUsed: str | None = Field(
        default=None, description="Additives used in processing, if available"
    )
    source: str | None = Field(
        default=None,
        description="Manufacturer or previous owners unique operator id, if available",
    )
    destination: str | None = Field(
        default=None, description="Destination of the product, if available"
    )
    receptionDate: str | None = Field(
        default=None, description="Date of reception of the product, if available"
    )


class TradeData(BaseModel):
    """Model to represent trade data in an IUU incident."""

    exporterInformation: str | None = Field(
        default=None, description="Information about the exporter, if available"
    )
    importerInformation: str | None = Field(
        default=None, description="Information about the importer, if available"
    )


class DistributionData(BaseModel):
    """Model to represent distribution data in an IUU incident."""

    firstBuyer: str | None = Field(
        default=None, description="Name of the first buyer, if available"
    )
    transportVehicleID: str | None = Field(
        default=None,
        description="ID of the transport vehicle used for distribution, if available",
    )
    productionDate: str | None = Field(
        default=None, description="Date of production, if available"
    )
    expiryDate: str | None = Field(
        default=None, description="Expiry date of the product, if available"
    )
    movementDate: str | None = Field(
        default=None, description="Date of movement of the product, if available"
    )


class ExtractedIncidentData(BaseModel):
    """Model to represent the structured information extracted from an article about an IUU incident."""

    catchSourceInformation: CatchSourceData | None = Field(
        default=None,
        description="Structured information about the  catch involved in the incident.",
    )
    aquactureInformation: AquacultureData | None = Field(
        default=None,
        description="Information on farmed fishery involved in incident, if available",
    )
    transshipmentInformation: TransshipmentData | None = Field(
        default=None,
        description="Structured information about transshipment involved in the incident, if available.",
    )
    aggregationInformation: AggregationData | None = Field(
        default=None,
        description="Structured information about aggregation involved in the incident, if available.",
    )
    landingInformation: LandingData | None = Field(
        default=None,
        description="Structured information about landing involved in the incident, if available.",
    )
    tradeInformation: TradeData | None = Field(
        default=None,
        description="Structured information about trade involved in the incident, if available.",
    )
    distributionInformation: DistributionData | None = Field(
        default=None,
        description="Structured information about distribution involved in the incident, if available.",
    )
    eventData: EventData | None = Field(
        default=None,
        description="Structured information about the primary event of the incident, if available.",
    )

    speciesInvolved: List[Species] = Field(
        description="List of species involved in the incident"
    )
    productsInvolved: List[ProductData] = Field(
        description="List of products involved in the incident"
    )

    chainOfCustody: str | None = Field(
        default=None, description="Chain of custody information, if available"
    )
    sanitaryLicenseID: str | None = Field(
        default=None, description="Sanitary license ID, if available"
    )

    description: str = Field(description="Short summary of the incident")


class IncidentClassification(BaseModel):
    """Model to represent the classification of an IUU incident."""

    iuuClassifications: List[IUUClassification] = Field(
        ...,
        description="A list of all applicable IUU classifications for the incident.",
    )


class IndustryOverviewExtract(BaseModel):
    """Model to represent the extraction of information from an industry overview article."""

    species: List[Species] = Field(
        ..., description="List of species mentioned in the overview."
    )
    countries: List[str] = Field(
        ..., description="List of countries mentioned in the overview."
    )
    companies: List[str] = Field(
        ..., description="List of companies mentioned in the overview."
    )
    incidents: List[ExtractedIncidentData] = Field(
        ..., description="List of incidents mentioned in the overview."
    )

    summary: str = Field(description="Summary of the industry overview article.")


class IndustryOverview(Document):
    """Model to represent an industry overview article."""

    source: Link["Source"] | None = None
    extracted_information: IndustryOverviewExtract

    class Settings:
        name = "industry_overviews"


class IncidentReport(Document):
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

    verified: bool = Field(default=False)

    class Settings:
        name = "incidents"

    @before_event([Insert, Replace])
    def generate_fingerprint(self):
        """Generate incident fingerprint before saving"""

        if not self.incident_fingerprint:
            eventData = self.extracted_information.eventData
            catchSourceInfo = self.extracted_information.catchSourceInformation

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
                catchSourceInfo.vesselName
                if catchSourceInfo and catchSourceInfo.vesselName
                else "default_vessel"
            )

            fingerprint_data = f"{name}_" f"{date}_" f"{location}"
            self.incident_fingerprint = hashlib.sha256(
                fingerprint_data.encode()
            ).hexdigest()

    async def add_source(self, source: "Source", is_primary: bool = False):
        """Helper method to add a source and maintain bidirectional relationship"""
        try:
            if self.sources is None:
                self.sources = []
            # Check if source is already in the list by comparing IDs
            source_ids = [s.id for s in self.sources if hasattr(s, "id")]
            if source.id not in source_ids:
                self.sources.append(source)

            if is_primary:
                self.primary_source = source

            await self.save()
            # Handle bidirectional relationship
            if source.incidents is None:
                source.incidents = []

            incident_ids = [i.id for i in source.incidents if hasattr(i, "id")]
            if self.id not in incident_ids:
                source.incidents.append(self)
                await source.save()

        except Exception as e:
            # Log error or handle as appropriate for your application
            raise Exception(f"Failed to add source to incident: {e}")

    async def remove_source(self, source: "Source"):
        """Helper method to remove a source and maintain bidirectional relationship"""
        try:
            # Remove from sources list
            self.sources = [s for s in self.sources if s.id != source.id]

            # Update primary source if needed
            if self.primary_source and self.primary_source.id == source.id:
                self.primary_source = self.sources[0] if self.sources else None

            # Update the source's incidents list
            if source.incidents:
                source.incidents = [i for i in source.incidents if i.id != self.id]
                await source.save()

            await self.save()
        except Exception as e:
            raise Exception(f"Failed to remove source from incident: {e}")

    async def delete(self):
        """Override delete method to handle source removal"""
        try:
            # Remove this incident from all sources
            for source in self.sources:
                self.remove_source(source)

            self.sources = []
            self.primary_source = None

            # Call the parent delete method
            await super().delete()
        except Exception as e:
            raise Exception(f"Failed to delete incident report: {e}")

    @classmethod
    async def find_potential_duplicates(
        cls, incident_data: "ExtractedIncidentData", threshold: float = 0.8
    ):
        # This is a placeholder - you'd implement your actual duplicate detection logic
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
