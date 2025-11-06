from __future__ import annotations
from datetime import datetime
from typing import List, Literal
from beanie import Insert, Link, Replace, before_event
from pydantic import BaseModel, Field, model_validator
import hashlib
from pymongo import ASCENDING, IndexModel
from app.audit.base import AuditedDocument
from app.models.incidents import IndustryOverview
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from app.models.incidents import IncidentReport


class IncidentPassage(BaseModel):
    """Model representing a single incident's target passage within a multi-incident article."""

    target_passage: str = Field(
        ...,
        description="The specific text passage that describes this unique incident (the key details about this particular incident)",
    )
    full_context: str = Field(
        ...,
        description="The complete article text for reference and context during extraction",
    )


class ArticleData(BaseModel):
    """Pydantic model for validated article data"""

    text: str | None = Field(
        ...,
        description="Clean, well-structured article text with proper paragraphs and formatting",
    )
    language: str | None = Field(
        default=None, description="Language of the article, eg. 'en' for English"
    )
    publication_date: datetime | None = Field(
        default=None, description="Publication date of the article, if available"
    )


class ArticleScopeClassification(BaseModel):
    """Model to represent the classification of an article."""

    articleType: Literal[
        "Single Incident",
        "Multiple Incidents",
        "Industry Overview",
        "Unrelated to IUU Fishing",
    ] = Field(
        ...,
        description=(
            "Classify the article scope:\n\n"
            "IUU+ includes: Illegal/unreported/unregulated fishing, labor abuse, seafood fraud/mislabeling, sanction avoidance, illegal aquaculture.\n\n"
            "INCIDENT = A specific action by an identified vessel, entity, or person (arrests, seizures, investigations, violations by named actors).\n\n"
            "Categories:\n"
            "- 'Unrelated to IUU Fishing': Article does not discuss IUU+ topics\n"
            "- 'Industry Overview': Discusses IUU+ but NO specific incidents (e.g., policy announcements, coast guard patrols, industry trends, legislation, general enforcement activities, death of sea animals without identified perpetrator)\n"
            "- 'Single Incident': ONE specific IUU+ incident with identified actor(s)\n"
            "- 'Multiple Incidents': TWO OR MORE distinct IUU+ incidents with identified actors\n\n"
            "Examples of Industry Overview (NOT incidents):\n"
            "- Coast guard conducts routine patrols\n"
            "- Government announces new fishing regulations\n"
            "- Sea turtle deaths reported (no perpetrator identified)\n"
            "- Industry analysis or statistics\n\n"
            "Examples of Incidents:\n"
            "- Two poachers arrested after chase (named individuals)\n"
            "- Vessel 'ABC' seized for illegal fishing\n"
            "- Company fined for seafood mislabeling"
        ),
    )
    confidence: float = Field(
        ..., description="Confidence score for the classification, between 0 and 1."
    )


class SourceExtraction(BaseModel):
    url: str | None = Field(default=None, description="URL of the article to analyze.")
    article_title: str | None = Field(
        default=None, description="Title of the article if available."
    )
    article_text: str = Field(
        ..., description="Text content of the article to analyze."
    )
    article_scope: ArticleScopeClassification | None = Field(
        default=None, description="Scope classification of the article"
    )

    author: str | None = Field(default=None, description="Author or organization")
    publisher: str | None = Field(
        default=None, description="Publisher of the article if available"
    )
    publication_date: datetime | None = Field(
        default=None, description="When the source was published"
    )

    seperated_incident_text: List[str] = Field(default_factory=list)


class Source(AuditedDocument):
    url: str | None = Field(default=None, description="URL of the article to analyze.")
    article_title: str | None = Field(
        default=None, description="Title of the article if available."
    )
    article_text: str = Field(
        ..., description="Text content of the article to analyze."
    )
    article_scope: ArticleScopeClassification | None = Field(
        default=None, description="Scope classification of the article"
    )

    validated_scope: bool | None = Field(default=False)

    seperated_incident_text: List[str] = Field(default_factory=list)

    # For multiple incidents: stores the separated passages with full context
    incident_passages: List["IncidentPassage"] | None = Field(
        default=None,
        description="For articles with multiple incidents, contains the target passage for each incident plus full article context",
    )

    article_hash: str = Field(
        default="", description="Hash of article text for deduplication"
    )

    # Information presence flags (for debugging and optimization)
    information_presence: dict | None = Field(
        default=None,
        description="Flags indicating which types of information are present in the article",
    )

    author: str | None = Field(default=None, description="Author or organization")
    publisher: str | None = Field(
        default=None, description="Publisher of the article if available"
    )
    publication_date: datetime | None = Field(
        default=None, description="When the source was published"
    )

    incidents: List[Link["IncidentReport"]] = Field(default_factory=list)
    overview: Link["IndustryOverview"] | None = None

    input_category: Literal["url", "text_upload", "pdf", "existing_extract"] = Field(
        default="url", description="Category of how the app received the source."
    )
    source_type: Literal[
        "government", "news", "industry report", "ngo", "academic", "not specified"
    ] = Field(default="not specified", description="description of who made the source")
    status: Literal["extracted", "from_api", "user_input", "modified"] = Field(
        default="extracted",
        description="Status of the source. Extracted means the fields were automatically extracted from source. User_input means the report was created by a user. Modified means the report was modified by a user after its creation.",
    )

    class Settings:
        name = "sources"
        indexes = [
            IndexModel([("article_hash", ASCENDING)], unique=True),
            IndexModel(
                [("url", ASCENDING)],
                unique=True,
                partialFilterExpression={"url": {"$type": "string"}},
            ),
            IndexModel([("article_text", "text")]),
        ]

    @model_validator(mode="after")
    def generate_hash_on_creation(self):
        """Generate article hash after model creation"""
        if not self.article_hash and self.article_text:
            self.article_hash = hashlib.sha256(self.article_text.encode()).hexdigest()
        return self

    @before_event([Insert, Replace])
    def generate_hash(self):
        """Generate article hash before saving"""
        if self.article_text:
            self.article_hash = hashlib.sha256(self.article_text.encode()).hexdigest()
        # self.updated_at = datetime.utcnow()

    async def delete(self):
        """Override delete method to prevent orphan incidents and clean up relationships"""
        try:
            # Import here to avoid circular imports
            from app.models.incidents import IncidentReport

            # Fetch all incidents linked to this source
            if self.incidents:
                for incident_link in self.incidents:
                    # Get the incident ID from the Link object
                    incident_id = (
                        incident_link.ref.id
                        if hasattr(incident_link, "ref")
                        else incident_link.id
                    )

                    if incident_id:
                        # Fetch incident without links to check source count
                        full_incident = await IncidentReport.get(
                            incident_id, fetch_links=False
                        )
                        if full_incident:
                            # Count how many sources this incident has
                            source_count = (
                                len(full_incident.sources)
                                if full_incident.sources
                                else 0
                            )

                            # If this is the only source, delete the incident
                            if source_count <= 1:
                                await full_incident.delete()
                            else:
                                # Remove this source from the incident's source list
                                await full_incident.remove_source(self)

            # Clean up overview relationship if it exists
            if self.overview:
                overview = await self.overview.fetch()
                if overview:
                    overview.source = None
                    await overview.save()

            # Clear relationships before deleting
            self.incidents = []
            self.overview = None

            # Call parent delete method
            await super().delete()
        except Exception as e:
            raise Exception(f"Failed to delete source: {e}")
