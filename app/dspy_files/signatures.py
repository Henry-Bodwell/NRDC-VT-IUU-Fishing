from datetime import datetime
from typing import List
import dspy
from pydantic import BaseModel, Field
from app.models.incidents import (
    ExtractedIncidentData,
    IncidentClassification,
    IndustryOverviewExtract,
)
from app.models.articles import ArticleScopeClassification, Source, SourceExtraction


class TextToStructuredData(dspy.Signature):
    """Signature to extract structured information from text."""

    source: Source = dspy.InputField(
        desc="Base source data containing URL and article text."
    )
    extracted_data: ExtractedIncidentData = dspy.OutputField()
    classification: IncidentClassification = dspy.OutputField()


class MultipleIncidentSignature(dspy.Signature):
    """Splits text into unique sets for extraction"""

    text: str = dspy.InputField(desc="Article Text with multiple IUU incidents")
    seperated_incident_text: List[str] = dspy.OutputField(
        desc="List of text regarding each unique incident metioned in article, ie if the article has 2 incidents this should have two items, with each item containing all relevant text referring to its incident."
    )


class MultipleIncidentToStructured(dspy.Signature):
    text: str = dspy.InputField(desc="Article Text to extract and classify")
    extracted_data: ExtractedIncidentData = dspy.OutputField()
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
