from datetime import datetime
from typing import List
import dspy
from app.models.incidents import (
    ExtractedIncidentData,
    IncidentClassification,
    IndustryOverviewExtract,
)
from app.models.articles import ArticleScopeClassification, Source


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
    source: Source = dspy.OutputField(desc="Source object with cleaned article text")
