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
        description="Select the type of article: if unrelated to Illegal, unregulated or unreported fishing, 'Unrelated to IUU Fishing', "
        "else if referring to a specific or multiple specific incidents of illegal fishing select 'Single Incident' or 'Multiple Incidents', "
        "otherwise if discussing illegal fishing but not referring to a specific case 'Industry Overview'",
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

    seperated_incident_text: List[str] = Field(default_factory=list)

    article_hash: str = Field(
        default="", description="Hash of article text for deduplication"
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

    category: Literal["url", "text_upload", "pdf", "academic"] = Field(
        default="url", description="Category of the source"
    )
    status: Literal["extracted", "user_input", "modified"] = Field(
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
                    # Fetch the linked incident if it's a Link object
                    incident = await incident_link.fetch() if hasattr(incident_link, 'fetch') else incident_link

                    if incident:
                        # Fetch full incident with all sources to check count
                        full_incident = await IncidentReport.get(incident.id, fetch_links=True)
                        if full_incident:
                            # Count how many sources this incident has
                            source_count = len(full_incident.sources) if full_incident.sources else 0

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
