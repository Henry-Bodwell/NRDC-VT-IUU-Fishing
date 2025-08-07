from datetime import datetime
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


class StructuredDataToClassification(dspy.Signature):
    """Classifier for IUU incidents."""

    incident_summary: str = dspy.InputField(desc="Summary of the incident to classify")
    structured_data: ExtractedIncidentData = dspy.InputField(
        desc="Structured data extracted from the incident"
    )
    classification: IncidentClassification = dspy.OutputField()


class ArticleClassificationSignature(dspy.Signature):
    """
    Classifies an article based on its content.
    """

    source: Source = dspy.InputField(
        desc="Base source data containing URL and article text to classify."
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
