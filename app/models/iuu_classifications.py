from typing import List, Literal

from pydantic import BaseModel, Field, model_validator

# Subtype definitions for each IUU type
ILLEGAL_FISHING_SUBTYPES = Literal[
    "Exceeding catch quotas",
    "Keeping undersized fish",
    "Catching unauthorized or prohibited species",
    "Prohibited fishing gear",
    "Fishing in closed areas or closed seasons",
    "Invalid or no permit or license",
    "Obscuring vessel identity",
    "Unauthorized transshipment",
    "Falisfying Documents",
    "Obstructing inspectors",
    "Illegal bycatch practices",
]

UNREPORTED_CATCH_SUBTYPES = Literal[
    "Un/underreported target catch weight or size",
    "Un/underreported discards/bycatch weight or size",
    "Misreported target catch species",
    "Misreported non-target catch species",
    "Misreported location or timing of fishing",
    "Misreported gear",
    "Unreported transshipment activities",
]

UNREGULATED_FISHING_SUBTYPES = Literal[
    "Stateless vessel",
    "Fishing under flag not party to RFMO",
    "Fishing in unregulated areas or for unregulated stock",
]

SEAFOOD_FRAUD_SUBTYPES = Literal[
    "Species mislabeling or fraud",
    "Production information fraud",
]

FORCED_LABOR_SUBTYPES = Literal[
    "Wage/Pay violations",
    "Abusive living conditions",
    "Abusive working conditions",
    "Inadequate crew size",
    "Physical or sexual violence",
    "Intimidation",
    "Families threatened",
    "Deception",
    "No work contracts",
    "Isolation",
    "Migrants threatened",
]

SANCTIONS_SUBTYPES = Literal[
    "Circumventing sanctions (individuals or corporations)",
    "Circumventing import prohibitions (countries or products)",
]

AQUACULTURE_SUBTYPES = Literal[
    "Unapproved/non-native species",
    "Illegal sourcing of seed/broodstock",
    "Misrepresentation or falsification of farming operations",
    "Unlicensed/Unauthorized farm operations",
    "Stolen products",
]

OTHER_SUBTYPES = Literal[
    "Information not sufficient to determine specific IUU+ behavior",
    "Crimes related to fishing or associated trade but distinct from IUU+ typology (e.g., murder of journalists investigating IUU+ fishing)",
    "Other",
]


# Base class that coerces empty lists to None so legacy DB records pass min_length=1 validation
class IUUClassificationBase(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _coerce_empty_lists_to_none(cls, data: object) -> object:
        if isinstance(data, dict):
            return {
                k: (None if isinstance(v, list) and len(v) == 0 else v)
                for k, v in data.items()
            }
        return data


# Individual classification models for each IUU type (discriminated union approach)
class IllegalFishingClassification(IUUClassificationBase):
    """Direct violations of fishing regulations"""

    IUUType: Literal["Illegal Fishing"] = "Illegal Fishing"
    IUUSubType: List[ILLEGAL_FISHING_SUBTYPES] | None = Field(
        default=None,
        min_length=1,
        description='ALL specific violations found. Options: "Exceeding catch quotas", '
        '"Keeping undersized fish", "Catching unauthorized or prohibited species", '
        '"Prohibited fishing gear", "Fishing in closed areas or closed seasons", '
        '"Invalid or no permit or license", "Obscuring vessel identity", "Unauthorized transhipment", '
        '"Falsifying Authorizations", "Obstructing inspectors", "Illegal bycatch practices"',
    )
    IUUTypeReason: str = Field(
        ...,
        min_length=1,
        description="Detailed explanation with specific evidence from the article for this illegal fishing violation.",
    )
    verified: bool = Field(default=False)


class UnreportedCatchClassification(IUUClassificationBase):
    """Failure to report or misreporting of catch data"""

    IUUType: Literal["Unreported Catch"] = "Unreported Catch"
    IUUSubType: List[UNREPORTED_CATCH_SUBTYPES] | None = Field(
        default=None,
        min_length=1,
        description='ALL violations found. Options: "Un/underreported target catch weight or size", '
        '"Un/underreported discards/bycatch weight or size", "Misreported target catch species", '
        '"Misreported non-target catch species", "Misreported location or timing of fishing", '
        '"Misreported gear", "Unreported transshipment activities"',
    )
    IUUTypeReason: str = Field(..., description="Detailed explanation with evidence.")
    verified: bool = Field(default=False)


class UnregulatedClassification(IUUClassificationBase):
    """Vessels operating outside regulatory frameworks"""

    IUUType: Literal["Unregulated Fishing"] = "Unregulated Fishing"
    IUUSubType: List[UNREGULATED_FISHING_SUBTYPES] | None = Field(
        default=None,
        min_length=1,
        description='ALL violations found. Options: "Stateless vessel", '
        '"Fishing under flag not party to RFMO", "Fishing in unregulated areas or for unregulated stock"',
    )
    IUUTypeReason: str = Field(..., description="Detailed explanation with evidence.")
    verified: bool = Field(default=False)


class SeafoodFraudClassification(IUUClassificationBase):
    """Fraudulent labeling or misrepresentation of seafood products"""

    IUUType: Literal["Seafood Fraud or Mislabeling"] = "Seafood Fraud or Mislabeling"
    IUUSubType: List[SEAFOOD_FRAUD_SUBTYPES] | None = Field(
        default=None,
        min_length=1,
        description='ALL violations found. Options: "Species mislabeling or fraud", '
        '"Production information fraud"',
    )
    IUUTypeReason: str = Field(..., description="Detailed explanation with evidence.")
    verified: bool = Field(default=False)


class ForcedLaborClassification(IUUClassificationBase):
    """Labor violations and abuse of crew members"""

    IUUType: Literal["Forced Labor or Labor Abuse"] = "Forced Labor or Labor Abuse"
    IUUSubType: List[FORCED_LABOR_SUBTYPES] | None = Field(
        default=None,
        min_length=1,
        description='ALL violations found. Options: "Wage/Pay violations", "Abusive living conditions", '
        '"Abusive working conditions", "Inadequate crew size", "Physical or sexual violence", "Intimidation", '
        '"Families threatened", "Deception", "No work contracts", "Isolation", "Migrants threatened"',
    )
    IUUTypeReason: str = Field(..., description="Detailed explanation with evidence.")
    verified: bool = Field(default=False)


class SanctionsClassification(IUUClassificationBase):
    """Circumventing international sanctions or prohibitions"""

    IUUType: Literal["Circumventing Prohibitions or Sanctions"] = (
        "Circumventing Prohibitions or Sanctions"
    )
    IUUSubType: List[SANCTIONS_SUBTYPES] | None = Field(
        default=None,
        min_length=1,
        description='ALL violations found. Options: "Circumventing sanctions (individuals or corporations)", '
        '"Circumventing import prohibitions (countries or products)"',
    )
    IUUTypeReason: str = Field(..., description="Detailed explanation with evidence.")
    verified: bool = Field(default=False)


class IllegalAquacultureClassification(IUUClassificationBase):
    """Violations in aquaculture/fish farming operations"""

    IUUType: Literal["Illegal Aquacultural Practices"] = (
        "Illegal Aquacultural Practices"
    )
    IUUSubType: List[AQUACULTURE_SUBTYPES] | None = Field(
        default=None,
        min_length=1,
        description='ALL violations found. Options: "Unapproved/non-native species", "Illegal sourcing of seed/broodstock", '
        '"Misrepresentation or falsification of farming operations", '
        '"Unlicensed/Unauthorized farm operations", "Stolen products"',
    )
    IUUTypeReason: str = Field(..., description="Detailed explanation with evidence.")
    verified: bool = Field(default=False)


class OtherIUUClassification(IUUClassificationBase):
    """Other IUU violations not covered by standard categories"""

    IUUType: Literal["Other"] = "Other"
    IUUSubType: List[OTHER_SUBTYPES] | None = Field(
        default=None,
        min_length=1,
        description='ALL violations found. Options "Information not sufficient to determine specific IUU+ behavior", "Other"',
    )
    IUUTypeReason: str = Field(
        ...,
        description="REQUIRED: Explain the violation and why it doesn't fit other categories. Provide specific evidence.",
    )
    verified: bool = Field(default=False)


# Discriminated union of all IUU classification types
# Pydantic will automatically select the correct model based on the IUUType field
IUUClassification = (
    IllegalFishingClassification
    | UnreportedCatchClassification
    | UnregulatedClassification
    | SeafoodFraudClassification
    | ForcedLaborClassification
    | SanctionsClassification
    | IllegalAquacultureClassification
    | OtherIUUClassification
)


class IncidentClassification(BaseModel):
    """Model to represent the classification of an IUU+ incident."""

    iuuClassifications: List[IUUClassification] = Field(
        ...,
        min_length=1,
        description="A list of all applicable IUU+ classifications for the incident.",
    )
