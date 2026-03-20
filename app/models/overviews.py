from __future__ import annotations
from typing import TYPE_CHECKING, List
from beanie import Link
from pydantic import BaseModel, Field
from pymongo import TEXT, IndexModel

from app.audit.base import AuditedDocument
from app.models.incident_data import ExtractedIncidentData, Species

if TYPE_CHECKING:
    from app.models.sources import Source


class IndustryOverviewExtract(BaseModel):
    """Model to represent the extraction of information from an industry overview article."""

    species: List[Species] = Field(
        ..., description="List of species mentioned in the overview."
    )
    countries: List[str] = Field(
        ..., description="List of countries mentioned in the overview."
    )
    companies: List[str] = Field(
        ..., description="List of companies mentioned in the overview."
    )
    incidents: List[ExtractedIncidentData] = Field(
        ..., description="List of incidents mentioned in the overview."
    )

    summary: str = Field(description="Summary of the industry overview article.")


class IndustryOverview(AuditedDocument):
    """Model to represent an industry overview article."""

    source: Link["Source"] | None = None
    extracted_information: IndustryOverviewExtract

    class Settings:
        name = "industry_overviews"
        max_nesting_depth = 1
        indexes = [
            IndexModel(
                [
                    ("extracted_information.species.speciesCommonName", TEXT),
                    ("extracted_information.species.scientificName", TEXT),
                    ("extracted_information.countries", TEXT),
                    ("extracted_information.summary", TEXT),
                ]
            ),
        ]

    async def delete(self):
        """Override delete method to handle source removal"""
        try:
            if self.source:
                self.source.overviews = None

            self.source = None

            # Call the parent delete method
            await super().delete()
        except Exception as e:
            raise Exception(f"Failed to delete industry report: {e}")
