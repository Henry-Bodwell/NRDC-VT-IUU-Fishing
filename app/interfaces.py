from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class GenRequest(BaseModel):
    url: str | None = None
    text: str | None = None
    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    publication_date: datetime | None = None
    user_id: str | None = None

    @model_validator(mode="after")
    def check_at_least_one_field(self):
        if not any([self.url, self.text]):
            raise ValueError("Either url or text must be provided")
        return self


class Filter(BaseModel):
    limit: int = Field(default=25, gt=0, le=100)
    skip: int = Field(default=0, ge=0)
    sort_by: Literal["created_at", "modified_at"] = Field(default="created_at")
    source_type: Literal["all", "url", "text_upload", "pdf"] = Field(default="all")
    verified: Literal["all", "true", "false"] = Field(default="all")


class IncidentFilters(Filter):
    status: Literal["all", "extracted", "user_input", "modified"] = Field(default="all")
    IUU_type: Literal[
        "Illegal Fishing",
        "Illegal Fishing Associated Activities",
        "Unreported Catch",
        "Unreported Catch Associated Activities",
        "Unregulated Actors",
        "Unregulated Areas or Stocks",
        "Seafood Fraud or Mislabeling",
        "Forced Labor or Labor Abuse",
        "Circumventing Prohibitions or Sanctions",
        "Illegal Aquacultural Practices",
        "Other",
        "all",
    ] = Field(default="all")


class SourceFilters(Filter):
    article_scope: Literal[
        "all", "single_incident", "multiple_incidents", "industry_overview", "unrelated"
    ] = Field(default="all")
    verified: Literal["all", "true", "false"] = Field(default="all")
