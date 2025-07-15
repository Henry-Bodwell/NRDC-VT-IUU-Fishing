from typing import Dict, List, Literal
import dspy
from pydantic import BaseModel, Field, ValidationError

# Pydantic models
class BaseIntake(BaseModel):
    """Base model for intake data."""
    url: str = Field(..., description="URL of the article to analyze.")
    article_text: str = Field(..., description="Text content of the article to analyze.")


class Species(BaseModel):
    """Model to represent a single species involved in an incident."""
    commonName: str = Field(..., description="The common name of the species (e.g., 'Bluefin Tuna').")
    scientificName: str = Field(..., description="The scientific name of the species (e.g., 'Thunnus thynnus').")
    ASFISCode: str | None = Field( default=None, description="ASFIS 3-Aplha code of the species, if available.")
    productType: str | None = Field( default=None, description="Form of the product (e.g., 'Fins', 'Fillets', 'Whole'), if available.")
    liveWeight: str | None = Field( default=None, description="Weight of the species when alive, if specified (e.g., '100 kg'), if available.")

class IUUClassification(BaseModel):
    IUUType: Literal["Illegal Fishing",
                     "Unreported Catch",
                     "Unregulated Actors",
                     "Unregulated Areas or Stocks",
                     "Fraud or Mislabeling of Species",
                     "Fraud or Mislabeling of Production Info",
                     "Fraud or Mislabeling of Processing Info",
                     "Wage or Pay Abuse",
                     "Excessive Overtime",
                     "Restriction of Movement against Crew",
                     "Abusive Living Conditions",
                     "Physical or Sexual Violence against Crew",
                     "Intimidation against Crew",
                     "Retention of ID of crew",
                     "Deceptive Labor Practices"
                     "Forced Isolation of Crew",
                     "Abuse of Vulnerble Human Populations",
                     "Cirumventing Prohibitions or Sanctions",
                     "Illegal Aquacultural Practices"] = Field(...)
    IUUTypeReason: str = Field(..., description="Reason for the IUU incident, e.g., overfishing, habitat destruction")



class CatchSourceData(BaseModel):
    """The structured information extracted from an article about catch and source of an incident."""

    # Who
    vesselName: str | None = Field(..., description="Name of the vessel involved")
    vesselUniqueID: str | None = Field(..., description="ID of the vessel involved")
    vesselFlag: str | None = Field(..., description="Flag state of the vessel involved")
    internationalRadioCallSign: str | None = Field( default=None, description="Call Sign of the vessel involved, if available")
    rmfoVesselNumber: str | None = Field( default=None, description="Regional Fisheries Management Organization (RFMO) vessel number, if available")
    satelitteVesselTrackingAuthority: str | None = Field( default=None, description="Authority responsible for satellite tracking of the vessel, if available")
    publicVesselRegistryLink: str | None = Field( default=None, description="Link to the public vessel registry, if available")
    vesselCaptain: str | None = Field( default=None, description="Name of the vessel captain, if available")
    vesselOwner: str | None = Field( default=None, description="Name of the vessel owner, if available")
    beneficialOwner: str | None = Field( default=None, description="Name of the beneficial owner of the vessel, if available")
    recruitmentAgency: str | None = Field( default=None, description="Recruitment agency for the crew, if available")
    recruitmentChannel: str | None = Field( default=None, description="Channel through which the crew was recruited, if available")
    tradeUnionWorkersOrganization: str | None = Field( default=None, description="Trade union or workers' organization, if available")
    migrantWorkers: bool | None = Field( default=None, description="Whether migrant workers were involved in the incident, if available")
    genderOfWorkers: str | None = Field( default=None, description="gender of workers involved, if available")
    crewList: List[str] | None = Field( default=None, description="List of crew members involved in the incident, if available")
    fisheryImporvementProject: str | None = Field( default=None, description="Fishery improvement project associated with the incident, if available")
    # When
    eventDate: str = Field(..., description="Date of the incident")
    vesselTripDates: str | None = Field( default=None, description="Dates of the vessel trip, if available")
    timeAtSea: str | None = Field( default=None, description="Time spent at sea during the incident, if available")
    # Where
    catchArea: str = Field(..., description="Area where the incident occurred")
    authoristionToFish: bool | None = Field( default=None, description="Authorisation to fish in the area, if available")
    validLicense: bool | None = Field( default=None, description="Whether the vessel had a valid fishing license, if available")
    licensedFishingArea: str | None = Field( default=None, description="Licensed fishing area, if available")
    coastalZoneEntryAndExit: str | None = Field( default=None, description="Coastal zone entry and exit information, if available")
    availabilityOfCatchCoordinates: str | None = Field( default=None, description="Catch coordinates, if available")
    AisVmsTracking: bool | None = Field( default=None, description="Whether AIS/VMS tracking was used, if available")

    # How
    fishingMethod: str | None = Field( default=None, description="Method of fishing used in the incident, if available")
    productionMethod: str | None = Field( default=None, description="Method of production used in the incident, if available")
    harvestCertification: str | None = Field( default=None, description="Whether harvest certification was obtained, if available")
    partyToUNFSA: bool | None = Field( default=None, description="Whether the vessel is a party to the United Nations Fish Stocks Agreement (UNFSA), if available")
    cardedUnderEUIUURegulation: bool | None = Field( default=None, description="Whether the vessel is carded under the EU IUU Regulation, if available")
    inNOAABinannualReport: bool | None = Field( default=None, description="Whether the vessel is in the NOAA annual report, if available")
    hasHumanWelfarePolicy: bool | None = Field( default=None, description="Whether the vessel has a human welfare policy, if available")
    humanWelfareStandards: str | None = Field( default=None, description="Human welfare standards followed by the vessel, if available")
    grievanceMechanism: str | None = Field( default=None, description="Grievance mechanism in place, if available")
    safetyInspection: bool | None = Field( default=None, description="Whether a safety inspection was conducted, if available")
    thirdPartyInspection: bool | None = Field( default=None, description="Whether third-party inspection was conducted, if available")
    healthSafetyRecords: str | None = Field( default=None, description="Health and safety records, if available")
    workContracts: bool | None = Field( default=None, description="Whether work contracts were provided, if available")
    hasWifi: bool | None = Field( default=None, description="Whether the vessel has Wi-Fi access, if available")

class TransshipmentData(BaseModel):
    """Model to represent transshipment data in an IUU incident."""
    vesselName: str | None = Field( default=None, description="Name of the transshipment vessel, if available")
    vesselUniqueID: str | None = Field( default=None, description="Unique ID of the transshipment vessel, if available")
    vesselFlag: str | None = Field( default=None, description="Flag state of the transshipment vessel, if available")
    vesselRegistration: str | None = Field( default=None, description="Registration of the transshipment vessel, if available")
    transshipmentDeclaration: bool | None = Field( default=None, description="Whether a transshipment declaration was made, if available")
    transshipmentAuthorization: bool | None = Field( default=None, description="Whether transshipment was authorized, if available")
    IMONumber: str | None = Field( default=None, description="International Maritime Organization (IMO) number of the transshipment vessel, if available")
    vesselMasterInformation: str | None = Field( default=None, description="Information about the vessel master, if available")
    datesOfTransshipment: str | None = Field( default=None, description="Dates of transshipment, if available")
    locationOfTransshipment: str | None = Field( default=None, description="Location of transshipment, if available")

class AggregationData(BaseModel):
    """Model to represent aggregation data in an IUU incident."""
    aggregatorName: str | None = Field( default=None, description="Name of the aggregator involved in the incident, if available")
    aggregatorID: str | None = Field( default=None, description="ID of the aggregator involved in the incident, if available")
    aggregatorLicense: str | None = Field( default=None, description="License of aggregator if available")

class LandingData(BaseModel):
    """Model to represent landing data in an IUU incident."""
    authorization: str | None = Field( default=None, description="Authorization for landing, if available")
    portEntryRequest: str | None = Field( default=None, description="Port entry request, if available")
    datesOfLanding: str | None = Field( default=None, description="Dates of landing, if available")
    portOfLanding: str | None = Field( default=None, description="Port of landing, if available")
    partyToPMSA: bool | None = Field( default=None, description="Whether the vessel is a party to the Port State Measures Agreement (PMSA), if available")

class ProductData(BaseModel):
    """Model to represent products in an IUU incident."""
    productType: str | None = Field( default=None, description="Type of product processed, if available")
    species: List[Species] | None = Field(default=None, description="List of species involved in the product, if available")
    HSCode: str | None = Field( default=None, description="Harmonized System (HS) code of the product, if available")
    SKU: str | None = Field( default=None, description="Stock Keeping Unit (SKU) of the product, if available")
    processedWeight: str | None = Field( default=None, description="Weight of the processed product, if available")
    processingLocation: str | None = Field( default=None, description="Location(s) of processing, if available")
    additivesUsed: str | None = Field( default=None, description="Additives used in processing, if available")
    source: str | None = Field( default=None, description="Source of the product, if available")
    destination: str | None = Field( default=None, description="Destination of the product, if available")
    receptionDate: str | None = Field( default=None, description="Date of reception of the product, if available")

class TradeData(BaseModel):
    """Model to represent trade data in an IUU incident."""
    exporterInformation: str | None = Field( default=None, description="Information about the exporter, if available")
    importerInformation: str | None = Field( default=None, description="Information about the importer, if available")

class DistributionData(BaseModel):
    """Model to represent distribution data in an IUU incident."""
    firstBuyer: str | None = Field( default=None, description="Name of the first buyer, if available")
    transportVehicleID: str | None = Field( default=None, description="ID of the transport vehicle used for distribution, if available")
    productionDate: str | None = Field( default=None, description="Date of production, if available")
    expiryDate: str | None = Field( default=None, description="Expiry date of the product, if available")
    movementDate: str | None = Field( default=None, description="Date of movement of the product, if available")


class ExtractedIncidentData(BaseModel):
    scopeOfArticle: str = Field(..., description="Is this about a single incident, multiple incidents, or an industry overview?")

    catchSourceInformation: CatchSourceData = Field(..., description="Structured information about the source / catch involved in the incident.")
    transshipmentInformation: TransshipmentData | None = Field( default=None, description="Structured information about transshipment involved in the incident, if applicable.")
    aggregationInformation: AggregationData | None = Field( default=None, description="Structured information about aggregation involved in the incident, if applicable.")
    landingInformation: LandingData | None = Field( default=None, description="Structured information about landing involved in the incident, if applicable.")
    tradeInformation: TradeData | None = Field( default=None, description="Structured information about trade involved in the incident, if applicable.")
    distributionInformation: DistributionData | None = Field( default=None, description="Structured information about distribution involved in the incident, if applicable.")

    speciesInvolved: List[Species] = Field(description="List of species involved in the incident")
    productsInvolved: List[ProductData] = Field(description="List of products involved in the incident")

    chainOfCustody: str | None = Field( default=None, description="Chain of custody information, if available")
    sanitaryLicenseID: str | None = Field( default=None, description="Sanitary license ID, if available")

    description: str = Field(description="Short summary of the incident")


class IncidentClassification(BaseModel):
    """Model to represent the classification of an IUU incident."""
    
    eventCategory: str = Field(..., description="Categorize the primary event (e.g., 'Seizure', 'Arrest', 'Investigation Initiated', 'Fine Issued').")
    resolution: str = Field(..., description="What was the outcome or resolution, if mentioned? (e.g., 'Vessel Detained', 'Crew Fined $10,000', 'Charges Dropped').")
    iuuClassifications: List[IUUClassification] = Field(..., description="A list of all applicable IUU classifications for the incident.")

class ArticleScopeClassification(BaseModel):
    """Model to represent the classification of an article."""
    
    articleType: Literal["Single Incident", "Multiple Incidents", "Industry Overview", "Unrelated to IUU Fishing"] = Field(..., description="Type of article: Single Incident of IUU fishing, Discussing Multiple Incidents of IUU fishing, aGeneral Overview of the state of illegal fishing but not related to an explicit incident or unrelated to IUU fishing.")
    confidence: float = Field(..., description="Confidence score for the classification, between 0 and 1.")

class IndustryOverviewExtract(BaseModel):
    """Model to represent the extraction of information from an industry overview article."""
    scopeOfArticle: Literal["Industry Overview"] = Field(description="Scope of the article, which is an industry overview.")

    species: List[Species] = Field(..., description="List of species mentioned in the overview.")
    countries: List[str] = Field(..., description="List of countries mentioned in the overview.")
    companies: List[str] = Field(..., description="List of companies mentioned in the overview.")
    incidents: List[ExtractedIncidentData] = Field(..., description="List of incidents mentioned in the overview.")
    
    summary: str = Field(description="Summary of the industry overview article.")

#Signatures for DSPy
class TextToStructuredData(dspy.Signature):
    """Signature to extract structured information from text."""
    
    intake: BaseIntake = dspy.InputField(desc="Base intake data containing URL and article text.")
    extracted_data: ExtractedIncidentData = dspy.OutputField()

class StructuredDataToClassification(dspy.Signature):
    """Classifier for IUU incidents."""
    
    incident_summary: str = dspy.InputField(desc="Summary of the incident to classify")
    structured_data: str = dspy.InputField(desc="Structured data extracted from the incident")
    classification: IncidentClassification = dspy.OutputField()

class CorrectionSignature(dspy.Signature):
    """
    Corrects a Pydantic object based on an error message and feedback.
    """
    original_object_json: str = dspy.InputField(desc="The original Pydantic object as a JSON string, which failed validation.")
    feedback: str = dspy.InputField(desc="The error message explaining why the object was incorrect.")
    corrected_object: Species = dspy.OutputField(desc="A new, corrected version of the Species object.")

class ArticleClassificationSignature(dspy.Signature):
    """
    Classifies an article based on its content.
    """
    intake: BaseIntake = dspy.InputField(desc="Base intake data containing URL and article text to classify.")
    classification: ArticleScopeClassification = dspy.OutputField(desc="The classification of the article, including type and confidence score.")

class IndustryOverviewSignature(dspy.Signature):
    """
    Extracts information from an industry overview article.
    """
    intake: BaseIntake = dspy.InputField(desc="Base intake data containing URL and article text for industry overview extraction.")
    extracted_data: IndustryOverviewExtract = dspy.OutputField(desc="Structured data extracted from the industry overview article.")


# DSPy Modules
class IncidentAnalysisModule(dspy.Module):
    """Module to extract and classify IUU incidents from text."""
    
    def __init__(self):
        super().__init__()

        self.extractor = dspy.ChainOfThought(TextToStructuredData)
        self.classifier = dspy.ChainOfThought(StructuredDataToClassification)

    def forward(self, intake: BaseIntake) -> Dict:
        """
        Extract structured information from the article text and classify the incident.
        """
        try:
            # Extract structured information
            extraction = self.extractor(intake=intake)
            
            # This output from the LLM could be a string OR already a Pydantic object
            structured_data_output = extraction.extracted_data


            # Classify the incident
            classification_pred = self.classifier(
                incident_summary=structured_data_output.description, 
                structured_data=structured_data_output.model_dump_json()
            )
            
            classification = classification_pred.classification
            return {
                "url": intake.url,
                "article_text": intake.article_text,
                "extraction": extraction,
                "parsed_data": structured_data_output,
                "classification": classification
            }
        except Exception as e:
            raise Exception(f"Error during extraction and classification: {str(e)}")

class IndustryOverviewModule(dspy.Module):
    """Module to extract information from industry overview articles."""
    
    def __init__(self):
        super().__init__()
        self.extractor = dspy.ChainOfThought(IndustryOverviewSignature)

    def forward(self, intake: BaseIntake) -> Dict:
        """
        Extract structured information from the industry overview article text.
        """
        try:
            extraction = self.extractor(intake=intake)
            
            return {
                "url": intake.url,
                "article_text": intake.article_text,
                "extraction": extraction,
                "parsed_data": extraction.extracted_data
            }
        except Exception as e:
            raise Exception(f"Error during industry overview extraction: {str(e)}")
