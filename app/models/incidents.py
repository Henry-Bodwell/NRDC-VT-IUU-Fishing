from __future__ import annotations
import hashlib
from typing import TYPE_CHECKING, List, Literal
from beanie import Document, Insert, Link, Replace, Update, before_event
from pydantic import BaseModel, Field
from datetime import datetime

from app.audit.base import AuditedDocument

if TYPE_CHECKING:
    from app.models.sources import Source


subtype_behavior = """
        {
            Illegal Fishing: ['Exceeding catch quotas', 'Keeping undersized fish', 'Catching unauthorized or prohibited species', 'Prohibited fishing gear', 'Fishing in closed areas or closed seasons'],
            Illegal Fishing Associated Activities: ['Invalid permit','Obscuring vessel identity', 'Unauthorized transhipment', 'falsifying documents, excepting fish/transshipment license', 'Objstructing inspectors', 'illegal bycatch practices'],
            Unreported Catch: ['Un/underreported catch weight', 'Un/underreported discards/bycatch', 'Misreported catch species', 'Misreported location', 'Misreported gear'],
            Unreported Catch Associated Activities: ['Unreported transshipment activities'],
            Unregulated Actors: ['Stateless vessel', 'Fishing under flag not party to RFMO'],
            Unregulated Areas or Stocks: ['Operating for stock or in places to avoid international regulation'],
            Seafood Fraud of Mislabeling: ['Species', 'Production information', 'Processing information'],
            Forced Labor or Labor Abuse: ['Wage/Pay', 'Excessive overtime', 'Restriction of movement', 'Abusive living conditions', 'Abusive working conditions', 'Violence', 'Intimidation', 'ID Rentention', 'Deception', 'Isolation', 'Abuse of Vulnerability'],
            Circumventing Prohibitions or Sanctions: ['Sanctions', 'Prohibitions'],
            Illegal Aquacultural Practices: ['Unapproved/non-native species', 'Illegal sourcing', 'Unlicensed/Unauthorized farm', 'Stolen Products']
        }
        - 
        """


# Pydantic models
class Species(BaseModel):
    """Model to represent a single species involved in an incident, if there is a product there should be a species."""

    verified: bool = Field(
        default=False,
        description="Whether the species identification has been verified by a human, leave false",
    )
    speciesCommonName: str | None = Field(
        default=None,
        description="The common name of the species (e.g., 'Bluefin Tuna').",
    )
    aggregateCommonName: str | None = Field(
        default=None,
        description="Common name aggregate for the species, for example: speciesCommonName:aggregateCommonName::hammerhead shark:shark, or north florida hoppers:shrimp",
    )
    scientificName: str | None = Field(
        default=None,
        description="The scientific name of the species (e.g., 'Thunnus thynnus').",
    )

    ASFISCode: str | None = Field(
        default=None, description="ASFIS 3-Aplha code of the species, if available."
    )
    liveWeight: str | None = Field(
        default=None,
        description="The estimated live weight of fishery products is derived from the landed or product weight by the application of certain factors and is designed to represent the actual weight of the fishery product as it was taken from the water and before being subjected to any processing or other operations, if specified (e.g., '100 kg').",
    )


class CrewMember(BaseModel):
    """Model to represent a crew member involved in an incident."""

    verified: bool = Field(
        default=False,
        description="Whether the Crew Section has been verified by a human, leave false",
    )
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
        "Unreported Catch Associated Activities",
        "Unregulated Actors",
        "Unregulated Areas or Stocks",
        "Seafood Fraud or Mislabeling",
        "Forced Labor or Labor Abuse",
        "Circumventing Prohibitions or Sanctions",
        "Illegal Aquacultural Practices",
        "Other",
    ] = Field(
        ...,
        description=f"Select the IUU type that best applies, see below for list of behaviors and related iuu type: {subtype_behavior}",
    )

    IUUSubType: List[str] | None = Field(
        default=None,
        description=f"The select subtypes associatedin article under given IUUType: {subtype_behavior}",
    )

    IUUTypeReason: str = Field(
        ...,
        description="Reason for the IUU incident, e.g., overfishing, habitat destruction, if other please specify what the IUU type should be and why.",
    )
    verified: bool = Field(
        default=False,
        description="Whether the IUU Classification Section has been verified by a human, leave false",
    )


class EventData(BaseModel):
    """Structured information about the primary event of an IUU incident. ie the event that triggered the article."""

    verified: bool = Field(
        default=False,
        description="Whether the Event Section has been verified by a human, leave false",
    )

    eventCategory: str = Field(
        ...,
        description="Categorize the primary event (e.g., 'Seizure', 'Arrest', 'Investigation Initiated', 'Fine Issued').",
    )
    eventDate: str | None = Field(
        default=None, description="Date of the primary event (e.g., '2023-10-01')."
    )
    eventLocation: str | None = Field(
        default=None,
        description="Where did the primary event occur? (e.g., 'Pacific Ocean', 'Port of XYZ').",
    )
    resolution: str = Field(
        ...,
        description="What was the outcome or resolution, if mentioned? (e.g., 'Vessel Detained', 'Crew Fined $10,000', 'Charges Dropped').",
    )


class VesselData(BaseModel):
    """Vessel identification, ownership, and tracking information."""

    verified: bool = Field(
        default=False,
        description="Whether the vessel information has been verified by a human, leave false",
    )

    # Vessel Identity
    vesselName: str | None = Field(
        default=None,
        description="The verbal moniker used to visually identify a fishing vessel and register it in official databases.",
    )
    vesselUniqueID: str | None = Field(
        default=None,
        description="A permanent, non-reusable identifier associated with a vessel for its entire existence, typically displayed as a physical marking (e.g., IMO Number).",
    )
    vesselFlag: str | None = Field(
        default=None, description="Flag state of the vessel involved, if available"
    )
    mmsiNumber: str | None = Field(
        default=None,
        description="A unique, nine-digit number used to identify a vessel in non-voice, automated maritime radio-based communication systems like DSC and AIS, if available",
    )
    internationalRadioCallSign: str | None = Field(
        default=None, description="Call Sign of the vessel involved, if available"
    )
    rmfoVesselNumber: str | None = Field(
        default=None,
        description="Regional Fisheries Management Organization (RFMO) vessel number, if available",
    )

    # Vessel Tracking
    satelitteVesselTrackingAuthority: str | None = Field(
        default=None,
        description="Authority responsible for satellite tracking of the vessel, if available",
    )
    publicVesselRegistryLink: str | None = Field(
        default=None, description="Link to the public vessel registry, if available"
    )
    AisVmsCoverageRate: str | None = Field(
        default=None,
        description="The percentage or rate of time the vessel was covered by AIS/VMS tracking, if available",
    )

    # Vessel Ownership
    vesselCaptain: str | None = Field(
        default=None, description="Name of the vessel captain, if available"
    )
    vesselOwner: str | None = Field(
        default=None, description="Name of the vessel owner, if available"
    )
    beneficialOwner: str | None = Field(
        default=None,
        description="The name, nationality, and ID numbers of the individual person(s), or the entity/company details, that ultimately benefit from or control the vessel or its operations, if available",
    )


class CrewLaborData(BaseModel):
    """Crew composition, recruitment, and labor welfare information."""

    verified: bool = Field(
        default=False,
        description="Whether the crew/labor information has been verified by a human, leave false",
    )

    # Crew Composition
    crewList: List[CrewMember] | None = Field(
        default=None,
        description="List of crew members involved in the incident, if available",
    )
    genderOfWorkers: str | None = Field(
        default=None, description="gender make up of crew involved, if available"
    )
    migrantWorkers: bool | None = Field(
        default=None,
        description="Whether migrant workers were involved in the incident, if available",
    )
    migrantWorkersDetails: str | None = Field(
        default=None, description="% of crew migrant workers make up, if available"
    )

    # Recruitment
    recruitmentAgency: bool | None = Field(
        default=None,
        description="Name of the recruitment agency for the crew, if available",
    )
    recruitmentChannel: str | None = Field(
        default=None,
        description="The type (government/private) and name of the channel used for crew recruitment, if available",
    )
    tradeUnionWorkersOrganization: str | None = Field(
        default=None,
        description="Name of trade union or workers' organization, if available",
    )

    # Labor Welfare
    hasHumanWelfarePolicy: bool | None = Field(
        default=None,
        description="Whether the vessel there is human welfare, labor, or anti-slavery policy in place on a vessel/trip, if available",
    )
    humanWelfareStandards: str | None = Field(
        default=None,
        description="The name of internationally recognized standards to which the vessel/trip's human welfare policy claims conformity, if available",
    )
    hasGrievanceMechanism: bool | None = Field(
        default=None,
        description="Whether a grievance mechanism is in place, if available",
    )
    grievanceMechanism: str | None = Field(
        default=None,
        description="Details on the grievance mechanism in place, if available",
    )

    # Inspections and Safety
    safetyInspection: bool | None = Field(
        default=None,
        description="Whether a safety inspection was conducted, if available",
    )
    safetyInspectionFindings: str | None = Field(
        default=None,
        description="Findings of the safety inspection, if available",
    )
    thirdPartyInspection: bool | None = Field(
        default=None,
        description="Whether independent third-party social inspections were performed, if available",
    )
    inspectionDetails: str | None = Field(
        default=None,
        description="Details on the third-party social inspection, if available",
    )
    healthSafetyRecords: str | None = Field(
        default=None,
        description="Details from Health and safety records on occurrence of accidents, illnesses, or fatalities, if available",
    )

    # Work Conditions
    workContracts: bool | None = Field(
        default=None, description="Whether work contracts were provided, if available"
    )
    workContractsDetails: str | None = Field(
        default=None,
        description="Information regarding the copies and proof of crew work contracts and wages paid, if available",
    )
    hasWifi: bool | None = Field(
        default=None, description="Whether the vessel has Wi-Fi access, if available"
    )


class CatchData(BaseModel):
    """Information about when, where, and how fishing occurred."""

    verified: bool = Field(
        default=False,
        description="Whether the catch information has been verified by a human, leave false",
    )

    # When
    catchDate: str | None = Field(
        default=None,
        description="The calendar date(s) when the seafood capture occurred during the vessel's voyage, if available",
    )
    vesselTripDates: str | None = Field(
        default=None,
        description="The calendar start and end dates of the vessel's voyage, from when the hold was last empty until the seafood is discharged, if available",
    )
    timeAtSea: str | None = Field(
        default=None, description="Time spent at sea during the incident, if available"
    )

    # Where
    catchArea: str | None = Field(
        default=None,
        description="The geographic location of harvest, specified by the FAO Major Fishing Area code, and identifying the jurisdiction as either a national Exclusive Economic Zone (including the name of the coastal country) or the High Seas, if available",
    )
    coastalZoneEntryAndExit: str | None = Field(
        default=None,
        description="The entry and exit points for a coastal zone, typically specified in the fishing license, if available",
    )
    availabilityOfCatchCoordinates: str | None = Field(
        default=None,
        description="The GPS coordinates for the catch location, if available",
    )

    # How
    fishingMethod: str | None = Field(
        default=None,
        description="The specific equipment used to extract or capture seafood from the water, if available",
    )
    productionMethod: str | None = Field(
        default=None,
        description="The categorization of the general harvest method on the spectrum ranging from wild-capture to captive-culture, if available",
    )
    harvestCertification: str | None = Field(
        default=None,
        description="The name of the harvest standards body and the unique identifier associated with the certified entity for the seafood, if available",
    )
    fisheryImporvementProject: str | None = Field(
        default=None,
        description="The publicly-listed name of the Fishery Improvement Project (FIP) relevant to the harvest event, if available",
    )


class ComplianceData(BaseModel):
    """Licensing, authorization, and regulatory compliance information."""

    verified: bool = Field(
        default=False,
        description="Whether the compliance information has been verified by a human, leave false",
    )

    # Licensing
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
        description="The period of time during which the fishing license is valid., if available",
    )
    licensedFishingArea: str | None = Field(
        default=None,
        description="The geographic area(s) covered by the license (e.g., a specific area, the flag state's entire EEZ, and/or the high seas), if available",
    )

    # Regulatory Status
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
        description="Whether the vessel is in the NOAA biannual report, if available",
    )


class AquacultureData(BaseModel):
    """Model to represent aquaculture data in an IUU incident."""

    verified: bool = Field(
        default=False,
        description="Whether the Aquaculture Section has been verified by a human, leave false",
    )
    organization: str | None = Field(
        default=None,
        description="The legal entity that owns the mill, hatchery, farm, or processor in an aquaculture context, if available",
    )

    farmName: str | None = Field(
        default=None, description="Name of the aquaculture farm, if available"
    )
    farmUniqueID: str | None = Field(
        default=None, description="Unique ID of the aquaculture farm, if available"
    )
    farmLocation: str | None = Field(
        default=None, description="Location of the aquaculture farm, if available"
    )
    farmGPSLocation: str | None = Field(
        default=None, description="GPS Location of the aquaculture farm, if available"
    )
    fingerlingHarvestDate: str | None = Field(
        default=None,
        description="Date on which fingerlngs were transferred to the grow out farm/pond, if available",
    )
    harvestDate: str | None = Field(
        default=None,
        description="The calendar date on which the seafood was harvested from the farm or cultivation area, if available",
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
    broodstockSource: str | None = Field(
        default=None,
        description="The origin of the broodstock (e.g., from farms or wild-caught), including the reception date, origin, and seller, if available.",
    )

    stockingQuantity: str | None = Field(
        default=None,
        description="Verifiable number of animals stocked in the production unit, if available.",
    )


class TransshipmentData(BaseModel):
    """Model to represent transshipment data in an IUU incident."""

    verified: bool = Field(
        default=False,
        description="Whether the Section has been verified by a human, leave false",
    )

    vesselName: str | None = Field(
        default=None, description="Name of the transshipment vessel, if available"
    )
    vesselUniqueID: str | None = Field(
        default=None, description="Unique ID of the transshipment vessel, if available"
    )
    vesselFlag: str | None = Field(
        default=None,
        description="The nation responsible for supervising the transshipment vessel's safety, operations, and catch transfer reporting, if available",
    )
    vesselRegistration: str | None = Field(
        default=None,
        description="Registration of the transshipment vessel, if available",
    )
    transshipmentAuthorization: str | None = Field(
        default=None,
        description="The unique number of the regulatory document that grants permission for the discharge of seafood from a fishing vessel to a transshipment vessel at sea, if available",
    )
    IMONumber: str | None = Field(
        default=None,
        description="International Maritime Organization (IMO) number of the transshipment vessel, if available",
    )
    datesOfTransshipment: str | None = Field(
        default=None, description="Dates of transshipment, if available"
    )
    locationOfTransshipment: str | None = Field(
        default=None, description="Location of transshipment, if available"
    )


class AggregationData(BaseModel):
    """Model to represent aquacultural aggregators in an IUU incident."""

    verified: bool = Field(
        default=False,
        description="Whether the Section has been verified by a human, leave false",
    )

    aggregatorName: str | None = Field(
        default=None,
        description="The name of the company or person that collects harvested seafood from multiple farms for distribution, if available",
    )
    aggregatorID: str | None = Field(
        default=None,
        description="ID of the aggregator involved in the incident, if available",
    )
    aggregatorLicense: str | None = Field(
        default=None,
        description="The license number generated by authorities that grants the aquaculture aggregator permission to operat, if available",
    )


class LandingData(BaseModel):
    """Model to represent landing data in an IUU incident."""

    verified: bool = Field(
        default=False,
        description="Whether the Section has been verified by a human, leave false",
    )

    authorization: str | None = Field(
        default=None,
        description="The unique number of the regulatory document that grants permission for the discharge of wild-capture seafood to a landing location, if available",
    )
    portEntryRequest: str | None = Field(
        default=None,
        description="The unique number of the document submitted by a fishing vessel to the relevant port or flag state authority, requesting formal authorization to enter a designated port and discharge its seafood catch, if available",
    )
    datesOfLanding: str | None = Field(
        default=None, description="Dates of landing, if available"
    )
    portOfLanding: str | None = Field(
        default=None,
        description="The location where the seafood was first discharged to land, if available",
    )
    partyToPMSA: bool | None = Field(
        default=None,
        description="Whether the vessel is a party to the Port State Measures Agreement (PMSA), if available",
    )


class ProductData(BaseModel):
    """Model to represent products in an IUU incident."""

    verified: bool = Field(
        default=False,
        description="Whether the Section has been verified by a human, leave false",
    )

    productType: str | None = Field(
        default=None,
        description="A commercial short-hand reference indicating the degree to which the seafood has been transformed from its original living form, if available",
    )
    species: List[Species] | None = Field(
        default=None,
        description="List of species, or species groups involved in the product, if available",
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
        default=None,
        description="Weight of the processed product in kgsc, if available",
    )
    processingLocation: str | None = Field(
        default=None,
        description="The history of countries where the seafood product has undergone processing, if available",
    )
    additivesUsed: str | None = Field(
        default=None,
        description="The list of additives used in the seafood product, which typically must be from an approved, authorized list., if available",
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

    verified: bool = Field(
        default=False,
        description="Whether the Section has been verified by a human, leave false",
    )

    exporterInformation: str | None = Field(
        default=None,
        description="The name of the entity exporting or re-exporting the product, if available",
    )
    importerName: str | None = Field(
        default=None,
        description="The name of the company importing the seafood product, if available",
    )
    importerAddress: str | None = Field(
        default=None,
        description="The address of the company importing the seafood product, if available",
    )
    importerPhoneNumber: str | None = Field(
        default=None,
        description="The telephone number of the company importing the seafood product, if available",
    )


class DistributionData(BaseModel):
    """Model to represent distribution data in an IUU incident."""

    verified: bool = Field(
        default=False,
        description="Whether the Section has been verified by a human, leave false",
    )

    firstBuyer: str | None = Field(
        default=None,
        description="The identity of the initial purchaser of the seafood product after landing, if available",
    )
    transportVehicleID: str | None = Field(
        default=None,
        description="An identifier for the vehicle used to transport the seafood product, if available",
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

    vesselInformation: VesselData | None = Field(
        default=None,
        description="Vessel identification, ownership, and tracking information.",
    )
    crewLaborInformation: CrewLaborData | None = Field(
        default=None,
        description="Crew composition, recruitment, and labor welfare information.",
    )
    catchInformation: CatchData | None = Field(
        default=None,
        description="Information about when, where, and how fishing occurred.",
    )
    complianceInformation: ComplianceData | None = Field(
        default=None,
        description="Licensing, authorization, and regulatory compliance information.",
    )
    aquacultureInformation: AquacultureData | None = Field(
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

    speciesInvolved: List[Species] | None = Field(
        default=None,
        description="List of ALL species involved in the incident. This is REQUIRED - always extract species when fish, seafood, marine animals, or aquatic products are mentioned. Include common name and/or scientific name for each species.",
    )
    productsInvolved: List[ProductData] | None = Field(
        default=None,
        description="List of products involved in the incident. If products are mentioned, corresponding species should be included in speciesInvolved.",
    )

    chainOfCustody: str | None = Field(
        default=None, description="Chain of custody information, if available"
    )
    sanitaryLicenseID: str | None = Field(
        default=None, description="Sanitary license ID, if available"
    )

    description: str | None = Field(
        default=None, description="Short summary of the incident"
    )


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


class IndustryOverview(AuditedDocument):
    """Model to represent an industry overview article."""

    source: Link["Source"] | None = None
    extracted_information: IndustryOverviewExtract

    class Settings:
        name = "industry_overviews"

    async def delete(self):
        """Override delete method to handle source removal"""
        try:
            if self.source:
                self.source.overviews = None

            self.source = None

            # Call the parent delete method
            await super().delete()
        except Exception as e:
            raise Exception(f"Failed to delete industry report: {e}")


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
    status: Literal["extracted", "user_input", "modified"] = Field(
        default="extracted",
        description="Status of the report. extracted means the fields were automatically extracted from source. User_input means the report was created by a user. Modified means the report was modified by a user after its creation.",
    )

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
            source_ids = [s.id for s in self.sources if hasattr(s, "id")]
            if source.id not in source_ids:
                self.sources.append(source)

            if is_primary:
                self.primary_source = source

            await self.save()

            incident_ids = [i.id for i in source.incidents if hasattr(i, "id")]
            if self.id not in incident_ids:
                source.incidents.append(self)
                await source.save()

        except Exception as e:
            raise Exception(f"Failed to add source to incident: {e}")

    async def remove_source(self, source: "Source"):
        """Helper method to remove a source and maintain bidirectional relationship"""
        try:
            self.sources = [s for s in self.sources if s.id != source.id]

            if self.primary_source and self.primary_source.id == source.id:
                self.primary_source = self.sources[0] if self.sources else None

            if source.incidents:
                source.incidents = [i for i in source.incidents if i.id != self.id]
                await source.save()

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

    @before_event([Update, Replace])
    async def set_modified(self):
        self.status = "modified"

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
