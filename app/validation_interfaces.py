from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.iuu_classifications import IncidentClassification
from app.models.overviews import IndustryOverviewExtract
from app.models.sources import ArticleScopeClassification


class VersionedRequest(BaseModel):
    expected_version: int = Field(..., ge=1)


class FlagValidationRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)


class TierAUpdateRequest(VersionedRequest):
    article_scope: ArticleScopeClassification
    validated_scope: bool = True
    article_title: str | None = None
    url: str | None = None
    article_text: str | None = None
    author: str | None = None
    publisher: str | None = None
    publication_date: datetime | None = None
    overview_id: str | None = None


class ReprocessValidationRequest(VersionedRequest):
    assumed_scope: Literal[
        "Single Incident",
        "Multiple Incidents",
        "Industry Overview",
        "Unrelated to IUU Fishing",
    ]


class ClassificationUpdateRequest(VersionedRequest):
    incident_classification: IncidentClassification


class SectionUpdateRequest(VersionedRequest):
    value: Any = None
    reviewed: bool = True


class SourceRelationshipRequest(VersionedRequest):
    target_id: str | None = None


class OverviewUpdateRequest(VersionedRequest):
    extracted_information: IndustryOverviewExtract


class AdminResolveFlagRequest(BaseModel):
    action: Literal["resume", "release"] = "resume"


class AdminValidationAccessRequest(BaseModel):
    can_validate: bool


class AdminRoleAccessRequest(BaseModel):
    is_admin: bool


class AdminReopenRequest(BaseModel):
    validator_id: str | None = None
