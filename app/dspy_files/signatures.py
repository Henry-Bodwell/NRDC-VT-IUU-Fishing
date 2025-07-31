import dspy
from app.models.incidents import (
    BaseIntake,
    ExtractedIncidentData,
    IncidentClassification,
    ArticleScopeClassification,
    Species,
    IndustryOverviewExtract,
)


class TextToStructuredData(dspy.Signature):
    """Signature to extract structured information from text."""

    intake: BaseIntake = dspy.InputField(
        desc="Base intake data containing URL and article text."
    )
    extracted_data: ExtractedIncidentData = dspy.OutputField()


class StructuredDataToClassification(dspy.Signature):
    """Classifier for IUU incidents."""

    incident_summary: str = dspy.InputField(desc="Summary of the incident to classify")
    structured_data: ExtractedIncidentData = dspy.InputField(
        desc="Structured data extracted from the incident"
    )
    classification: IncidentClassification = dspy.OutputField()


class CorrectionSignature(dspy.Signature):
    """
    Corrects a Pydantic object based on an error message and feedback.
    """

    original_object_json: str = dspy.InputField(
        desc="The original Pydantic object as a JSON string, which failed validation."
    )
    feedback: str = dspy.InputField(
        desc="The error message explaining why the object was incorrect."
    )
    corrected_object: Species = dspy.OutputField(
        desc="A new, corrected version of the Species object."
    )


class ArticleClassificationSignature(dspy.Signature):
    """
    Classifies an article based on its content.
    """

    intake: BaseIntake = dspy.InputField(
        desc="Base intake data containing URL and article text to classify."
    )
    classification: ArticleScopeClassification = dspy.OutputField(
        desc="The classification of the article, including type and confidence score."
    )


class IndustryOverviewSignature(dspy.Signature):
    """
    Extracts information from an industry overview article.
    """

    intake: BaseIntake = dspy.InputField(
        desc="Base intake data containing URL and article text for industry overview extraction."
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
    clean_article = dspy.OutputField(
        desc="Clean, well-structured article text with proper paragraphs and formatting"
    )
