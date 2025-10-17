from datetime import datetime
from typing import List
import dspy
from pydantic import BaseModel, Field
from app.models.incidents import (
    ExtractedIncidentData,
    IncidentClassification,
    IndustryOverviewExtract,
    VesselData,
    CrewLaborData,
    CatchData,
    ComplianceData,
    Species,
    EventData,
    TransshipmentData,
    AquacultureData,
    TradeData,
    DistributionData,
    AggregationData,
    LandingData,
    ProductData,
)
from app.models.sources import (
    ArticleScopeClassification,
    Source,
    SourceExtraction,
    IncidentPassage,
)


class TextToStructuredData(dspy.Signature):
    """Signature to extract structured information from text."""

    source: Source = dspy.InputField(
        desc="Base source data containing URL and article text."
    )
    extracted_data: ExtractedIncidentData = dspy.OutputField(
        desc="Structured incident data. ALWAYS extract species information when fish, seafood, or marine animals are mentioned in the article."
    )
    classification: IncidentClassification = dspy.OutputField()


class MultipleIncidentSignature(dspy.Signature):
    """Identifies and extracts individual incident passages from a multi-incident article.

    For each unique incident mentioned, extracts:
    1. target_passage: The core text describing that specific incident
    2. full_context: The complete article for context

    This allows the extraction pipeline to focus on the target passage while having
    access to the full article for context and cross-references.
    """

    text: str = dspy.InputField(desc="Article text containing multiple IUU incidents")
    incident_passages: List[IncidentPassage] = dspy.OutputField(
        desc="List of incident passages, one for each unique incident. Each contains the target passage for that incident plus the full article context. If article has 2 incidents, return 2 IncidentPassage objects."
    )


class MultipleIncidentToStructured(dspy.Signature):
    text: str = dspy.InputField(desc="Article Text to extract and classify")
    extracted_data: ExtractedIncidentData = dspy.OutputField(
        desc="Structured incident data. ALWAYS extract species information when fish, seafood, or marine animals are mentioned in the text."
    )
    classification: IncidentClassification = dspy.OutputField()


class ArticleClassificationSignature(dspy.Signature):
    """
    Classifies an article based on its content.
    """

    source: Source = dspy.InputField(
        desc="Base source data containing article text to classify."
    )
    classification: ArticleScopeClassification = dspy.OutputField(
        desc="The classification of the article, including type and confidence score."
    )


class IndustryOverviewSignature(dspy.Signature):
    """
    Extracts information from an industry overview article.
    """

    source: Source = dspy.InputField(
        desc="Base source data containing URL and article text for industry overview extraction."
    )
    extracted_data: IndustryOverviewExtract = dspy.OutputField(
        desc="Structured data extracted from the industry overview article."
    )


# DSPy signature for content cleaning
class CleanArticleContent(dspy.Signature):
    """Clean and structure filtered HTML content into readable article text"""

    filtered_html = dspy.InputField(
        desc="Filtered HTML containing mainly textual content from article"
    )
    sourceExtract: SourceExtraction = dspy.OutputField(
        desc="Source object with cleaned article text"
    )


# Information presence detection
class InformationPresence(BaseModel):
    """Flags indicating which types of information are present in the article."""

    has_vessel_info: bool = Field(
        default=False,
        description="Does article mention vessel details (name, flag, identifiers, ownership)?",
    )
    has_crew_labor_info: bool = Field(
        default=False,
        description="Does article mention crew members, recruitment, labor conditions, or welfare policies?",
    )
    has_catch_info: bool = Field(
        default=False,
        description="Does article specify when/where/how fishing occurred (dates, locations, methods)?",
    )
    has_compliance_info: bool = Field(
        default=False,
        description="Does article mention licenses, permits, or regulatory compliance status?",
    )
    has_species_info: bool = Field(
        default=False,
        description="Does article mention specific fish species or catch details?",
    )
    has_event_details: bool = Field(
        default=False,
        description="Does article describe an enforcement event (seizure, arrest, fine, investigation)?",
    )
    has_transshipment: bool = Field(
        default=False,
        description="Does article mention transshipment or transfer of catch between vessels?",
    )
    has_aquaculture: bool = Field(
        default=False,
        description="Does article involve fish farms or aquaculture operations?",
    )
    has_trade_distribution: bool = Field(
        default=False,
        description="Does article mention seafood trade, import/export, or distribution chains?",
    )
    has_iuu_classification: bool = Field(
        default=False,
        description="Does article clearly describe illegal, unreported, or unregulated fishing activities?",
    )


class InformationPresenceSignature(dspy.Signature):
    """Identifies which categories of information are present in an article about IUU fishing."""

    text: str = dspy.InputField(desc="Article text to analyze for information presence")
    presence: InformationPresence = dspy.OutputField(
        desc="Flags indicating which types of information are present in the article"
    )


class ClassifyIncident(dspy.Signature):
    text: str = dspy.InputField(desc="Article text to classify")
    classication: IncidentClassification = dspy.OutputField()


# ==========================================
# Focused Extraction Signatures
# ==========================================
# These signatures are used for conditional extraction based on presence detection


class ExtractVesselData(dspy.Signature):
    """Extract detailed vessel identification, ownership, and tracking information from text."""

    text: str = dspy.InputField(desc="Article text containing vessel information")
    vessel_data: VesselData = dspy.OutputField(
        desc="Extracted vessel details including name, identifiers, flag state, ownership, and tracking information"
    )


class ExtractCrewLaborData(dspy.Signature):
    """Extract crew composition, recruitment, labor welfare, and working conditions information from text."""

    text: str = dspy.InputField(desc="Article text containing crew/labor information")
    crew_labor_data: CrewLaborData = dspy.OutputField(
        desc="Extracted crew member details, recruitment channels, welfare policies, inspections, and work conditions"
    )


class ExtractCatchData(dspy.Signature):
    """Extract information about when, where, and how fishing occurred from text."""

    text: str = dspy.InputField(desc="Article text containing catch information")
    catch_data: CatchData = dspy.OutputField(
        desc="Extracted fishing dates, locations, areas, methods, and certification details"
    )


class ExtractComplianceData(dspy.Signature):
    """Extract licensing, authorization, and regulatory compliance information from text."""

    text: str = dspy.InputField(desc="Article text containing compliance information")
    compliance_data: ComplianceData = dspy.OutputField(
        desc="Extracted fishing licenses, authorizations, regulatory status, and compliance with international agreements"
    )


class ExtractSpeciesData(dspy.Signature):
    """Extract all fish species and marine animals mentioned in the text."""

    text: str = dspy.InputField(
        desc="Article text mentioning fish species or marine animals"
    )
    species_list: List[Species] = dspy.OutputField(
        desc="List of ALL species mentioned with common names, scientific names, and weight information. REQUIRED when fish/seafood are mentioned."
    )


class ExtractEventData(dspy.Signature):
    """Extract information about the primary enforcement or regulatory event from text."""

    text: str = dspy.InputField(desc="Article text describing an enforcement event")
    event_data: EventData = dspy.OutputField(
        desc="Extracted event category (seizure, arrest, investigation, fine), date, location, and resolution"
    )


class ExtractTransshipmentData(dspy.Signature):
    """Extract transshipment vessel and transfer operation information from text."""

    text: str = dspy.InputField(
        desc="Article text containing transshipment information"
    )
    transshipment_data: TransshipmentData = dspy.OutputField(
        desc="Extracted transshipment vessel details, authorization, dates, and locations of transfer operations"
    )


class ExtractAquacultureData(dspy.Signature):
    """Extract fish farm and aquaculture operation information from text."""

    text: str = dspy.InputField(desc="Article text containing aquaculture information")
    aquaculture_data: AquacultureData = dspy.OutputField(
        desc="Extracted farm details, organization, location, harvest dates, farming methods, and broodstock sources"
    )


class ExtractTradeDistributionData(dspy.Signature):
    """Extract seafood trade, distribution, aggregation, and landing information from text."""

    text: str = dspy.InputField(
        desc="Article text containing trade/distribution information"
    )
    trade_data: TradeData = dspy.OutputField(
        desc="Extracted importer/exporter information and contact details"
    )
    distribution_data: DistributionData = dspy.OutputField(
        desc="Extracted buyer information, transport details, and product dates"
    )
    aggregation_data: AggregationData = dspy.OutputField(
        desc="Extracted aggregator information for aquaculture products"
    )
    landing_data: LandingData = dspy.OutputField(
        desc="Extracted landing authorization, port information, and dates"
    )


class ExtractProductData(dspy.Signature):
    """Extract seafood product information from text."""

    text: str = dspy.InputField(desc="Article text containing product information")
    products: List[ProductData] = dspy.OutputField(
        desc="List of seafood products with type, species, HS code, weight, processing details, and destination"
    )


class ExtractIUUClassification(dspy.Signature):
    """Classify the type of IUU (Illegal, Unreported, Unregulated) fishing activity described in the text."""

    text: str = dspy.InputField(desc="Article text describing IUU fishing activities")
    classification: IncidentClassification = dspy.OutputField(
        desc="Classification of IUU types and subtypes with reasoning based on the incident behaviors"
    )
