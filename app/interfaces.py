from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, Field, model_validator

from app.literals import (
    ArticleScope,
    InputType,
    IUUSubtype,
    IUUType,
    LocationCategory,
    SourceType,
    Status,
)


class GenRequest(BaseModel):
    url: str | None = None
    text: str | None = None
    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    publication_date: datetime | None = None
    user_id: str | None = None
    source_type: SourceType = Field(
        default="not specified", description="Type of source organization"
    )
    status: Status = Field(
        default="all",
        description="Status of the source (extracted, from_api, user_input, or modified)",
    )
    input_name: str | None = None

    @model_validator(mode="after")
    def check_at_least_one_field(self):
        if not any([self.url, self.text]):
            raise ValueError("Either url or text must be provided")
        return self


class Filter(BaseModel):
    # Pagination
    limit: int = Field(default=25, gt=0, le=100)
    skip: int = Field(default=0, ge=0)

    # Sorting
    sort_by: Literal["created_at", "modified_at"] = Field(default="created_at")
    sort_order: Literal["asc", "desc"] = Field(
        default="desc", description="Sort order: ascending or descending"
    )

    # Common filters
    input_category: InputType = Field(default="all")
    verified: Literal["all", "true", "false"] = Field(default="all")

    # Date range filters
    created_after: datetime | None = Field(
        default=None,
        description="Filter records created after this date (ISO 8601 format)",
    )
    created_before: datetime | None = Field(
        default=None,
        description="Filter records created before this date (ISO 8601 format)",
    )
    modified_after: datetime | None = Field(
        default=None,
        description="Filter records modified after this date (ISO 8601 format)",
    )
    modified_before: datetime | None = Field(
        default=None,
        description="Filter records modified before this date (ISO 8601 format)",
    )

    # User filters
    created_by: str | None = Field(
        default=None, description="Filter by user who created the record"
    )
    modified_by: str | None = Field(
        default=None, description="Filter by user who last modified the record"
    )
    # Search
    search: str | None = Field(default=None, description="term to search for")

    status: Status = Field(default="all")


class IncidentFilters(Filter):
    IUU_type: IUUType = Field(default="all", description="Filter by IUU incident type")
    IUU_subtype: List[IUUSubtype] | None = Field(
        default=None, description="Filter by one or more IUU subtypes (multi-select)"
    )

    # Event date filters
    event_date_after: str | None = Field(
        default=None,
        description="Filter by event date after (extracted_information.eventData.eventDate)",
    )
    event_date_before: str | None = Field(
        default=None,
        description="Filter by event date before (extracted_information.eventData.eventDate)",
    )

    # Event Location filters
    event_location: str | None = Field(
        default=None, description="Filter by event location (partial match)"
    )
    event_country: str | None = Field(
        default=None, description="Filter by event country, ISO Alpha 3"
    )
    event_location_category: LocationCategory = Field(
        default="all", description="Filter by event location category"
    )
    # Enforcement Location filters
    enforcement_location: str | None = Field(
        default=None, description="Filter by  location (partial match)"
    )
    enforcement_country: str | None = Field(
        default=None, description="Filter by  country, ISO Alpha 3"
    )
    enforcement_location_category: LocationCategory = Field(
        default="all", description="Filter by  location category"
    )

    # Vessel filters
    vessel_name: str | None = Field(
        default=None, description="Filter by vessel name (partial match)"
    )
    vessel_flag: str | None = Field(
        default=None, description="Filter by vessel flag state"
    )

    # Species filter
    species_common_name: str | None = Field(
        default=None, description="Filter by species common name (partial match)"
    )

    # Enforcement category filter
    enforcement_category: str | None = Field(
        default=None,
        description="Filter by enforcement category (e.g., 'Seizure', 'Arrest', 'Fine Issued')",
    )


class SourceFilters(Filter):
    article_scope: ArticleScope = Field(default="all")
    source_type: SourceType = Field(
        default="all", description="Filter by source organization type"
    )
    verified: Literal["all", "true", "false"] = Field(default="all")

    # Publication date filters
    publication_date_after: datetime | None = Field(
        default=None, description="Filter sources published after this date"
    )
    publication_date_before: datetime | None = Field(
        default=None, description="Filter sources published before this date"
    )


# ── Request bodies ────────────────────────────────────────────────


class AddSourceRequest(BaseModel):
    """Request body for adding a source to an incident report."""

    source_id: str = Field(..., description="ID of the source to link")
    is_primary: bool = Field(
        default=False, description="Whether this is the primary source"
    )
