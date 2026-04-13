from typing import Literal

# ── Literal types for specific fields ──────────────────────────────
ArticleScope = Literal[
    "Single Incident",
    "Multiple Incidents",
    "Industry Overview",
    "Unrelated to IUU Fishing",
    "all",
]

IUUType = Literal[
    "Illegal Fishing",
    "Unreported Catch",
    "Unregulated Fishing",
    "Seafood Fraud or Mislabeling",
    "Forced Labor or Labor Abuse",
    "Circumventing Prohibitions or Sanctions",
    "Illegal Aquacultural Practices",
    "Other",
    "all",
]

IUUSubtype = Literal[
    # Illegal Fishing subtypes
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
    # Unreported Catch subtypes
    "Un/underreported target catch weight or size",
    "Un/underreported discards/bycatch weight or size",
    "Misreported target catch species",
    "Misreported non-target catch species",
    "Misreported location or timing of fishing",
    "Misreported gear",
    "Unreported transshipment activities",
    # Unregulated Fishing subtypes
    "Stateless vessel",
    "Fishing under flag not party to RFMO",
    "Fishing in unregulated areas or for unregulated stock",
    # Seafood Fraud subtypes
    "Species mislabeling or fraud",
    "Production information fraud",
    # Forced Labor subtypes
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
    # Sanctions subtypes
    "Circumventing sanctions (individuals or corporations)",
    "Circumventing import prohibitions (countries or products)",
    # Aquaculture subtypes
    "Unapproved/non-native species",
    "Illegal sourcing of seed/broodstock",
    "Misrepresentation or falsification of farming operations",
    "Unlicensed/Unauthorized farm operations",
    "Stolen products",
    # Other subtype
    "Information not sufficient to determine specific IUU+ behavior",
    "Crimes related to fishing or associated trade but distinct from IUU+ typology (e.g., murder of journalists investigating IUU+ fishing)",
    "Other",
    # Catch All
    "all",
]

SourceType = Literal[
    "all",
    "government",
    "news",
    "industry report",
    "ngo",
    "academic",
    "not specified",
]

Status = Literal["all", "extracted", "from_api", "user_input", "modified"]
