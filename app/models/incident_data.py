from typing import List, Literal

from pydantic import BaseModel, Field


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


class EventData(BaseModel):
    """Structured information about the primary event and enforcement act of an IUU+ incident. ie the event that triggered the article."""

    verified: bool = Field(
        default=False,
        description="Whether the Event Section has been verified by a human, leave false",
    )

    enforcementCategory: str | None = Field(
        default=None,
        description="Categorize the enforcement event (e.g., 'Seizure', 'Arrest', 'Investigation Initiated', 'Fine Issued').",
    )
    eventDate: str | None = Field(
        default=None, description="Date of the primary event (e.g., '2023-10-01')."
    )
    eventLocation: str | None = Field(
        default=None,
        description="Where did the primary event occur? (e.g., 'Pacific Ocean', 'Port of XYZ').",
    )
    eventCountry: str | None = Field(
        default=None,
        description="What is the alpha 3 code of the country where this event was? NA if The primary event did not occur in a country",
    )
    eventLocationCategory: (
        Literal["EEZ", "High Seas", "Inland Water", "Land"] | None
    ) = Field(default=None, description="Category of where the primary act took place")

    enforcementLocation: str | None = Field(
        default=None,
        description="Where did the enforcement event occur? Where were the people caught if so (e.g., 'Somali EEZ', 'Port of XYZ').",
    )
    enforcementCountry: str | None = Field(
        default=None,
        description="What is the alpha 3 code of the country where this enforcement event was? NA if The enforcement event did not occur in a country",
    )
    enforcementLocationCategory: (
        Literal["EEZ", "High Seas", "Inland Water", "Land"] | None
    ) = Field(
        default=None, description="Category of where the enforcement act took place"
    )

    primaryOffender: Literal["Vessel", "Corporate Actor", "Individual"] | None = Field(
        default=None, description="Who was the primary actor"
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


class CrewData(BaseModel):
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
    recruitmentAgency: str | None = Field(
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


class LaborStandards(BaseModel):
    validated: bool = Field(
        default=False,
        description="Whether the labor standards information has been verified by a human, leave false",
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
    catchCountry: str | None = Field(
        default=None, description="Country where the catch was made, if available"
    )
    coastalZoneEntryAndExit: str | None = Field(
        default=None,
        description="The entry and exit points for a coastal zone, typically specified in the fishing license, if available",
    )
    catchCoordinates: str | None = Field(
        default=None,
        description="The GPS coordinates for the catch location, if available",
    )
    AisVmsCoverageRate: str | None = Field(
        default=None,
        description="The percentage or rate of time the vessel was covered by AIS/VMS tracking, if available",
    )

    # How
    fishingMethod: str | None = Field(
        default=None,
        description="The specific equipment used to extract or capture seafood from the water, if available",
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
    licensedDateRange: str | None = Field(  # Change to start and end date
        default=None,
        description="The period of time during which the fishing license is valid, if available",
    )
    licensedFishingArea: str | None = Field(
        default=None,
        description="The geographic area(s) covered by the license (e.g., a specific area, the flag state's entire EEZ, and/or the high seas), if available",
    )
    harvestCertification: str | None = Field(
        default=None,
        description="The name of the harvest standards body and the unique identifier associated with the certified entity for the seafood, if available",
    )
    fisheryImporvementProject: str | None = Field(
        default=None,
        description="The publicly-listed name of the Fishery Improvement Project (FIP) relevant to the harvest event, if available",
    )

    # Regulatory Status
    partyToUNFSA: bool | None = Field(
        description="Whether the vessel is a party to the United Nations Fish Stocks Agreement (UNFSA), if available",
    )
    partyToPSMA: bool | None = Field(
        default=None,
        description="Whether the vessel is a party to the Port State Measures Agreement (PSMA), if available",
    )
    cardedUnderEUIUURegulation: bool | None = Field(
        default=None,
        description="Whether the vessel is carded under the EU IUU+ Regulation, if available",
    )
    inNOAABinannualReport: bool | None = Field(
        default=None,
        description="Whether the vessel is in the NOAA biannual report, if available",
    )


class AquacultureData(BaseModel):
    """Model to represent aquaculture data in an IUU+ incident."""

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
    """Model to represent transshipment data in an IUU+ incident."""

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
    countryOfTransshipment: str | None = Field(
        default=None, description="Country of transshipment, if available"
    )


class AggregationData(BaseModel):
    """Model to represent aquacultural aggregators in an IUU+ incident."""

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
    """Model to represent landing data in an IUU+ incident."""

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


class ProductData(BaseModel):
    """Model to represent products in an IUU+ incident."""

    verified: bool = Field(
        default=False,
        description="Whether the Section has been verified by a human, leave false",
    )

    productType: str | None = Field(
        default=None,
        description="A commercial short-hand reference indicating the degree to which the seafood has been transformed from its original living form, if available",
    )
    productionMethod: str | None = Field(
        default=None,
        description="The categorization of the general harvest method on the spectrum ranging from wild-capture to captive-culture, if available",
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
    """Model to represent trade data in an IUU+ incident."""

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
    """Model to represent distribution data in an IUU+ incident."""

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
    """Model to represent the structured information extracted from an article about an IUU+ incident."""

    vesselInformation: VesselData | None = Field(
        default=None,
        description="Vessel identification, ownership, and tracking information.",
    )
    crewInformation: CrewData | None = Field(
        default=None,
        description="Crew composition and recruitment information.",
    )
    laborStandards: LaborStandards | None = Field(
        default=None,
        description="Labor welfare policies, safety inspections, and working conditions.",
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
