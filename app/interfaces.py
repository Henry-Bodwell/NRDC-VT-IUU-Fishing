from typing import Literal
from pydantic import BaseModel, Field, model_validator


class GenRequest(BaseModel):
    url: str | None = None
    text: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def check_at_least_one_field(self):
        if not any([self.url, self.text]):
            raise ValueError("Either url or text must be provided")
        return self


class IncidentFilters(BaseModel):
    limit: int = Field(default=25, gt=0, le=25)
    skip: int = Field(default=0, ge=0)
    sort_by: Literal["created_at", "modified_at", "event_date"] = Field(
        default="event_date"
    )
    source_type: Literal["all", "url", "text_upload", "pdf"] = Field(default="all")
    verified: Literal["all", "true", "false"] = Field(default="all")
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
