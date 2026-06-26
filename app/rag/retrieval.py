"""Category-scoped retrieval for the extraction pipeline.

Each focused DSPy extractor (vessel, crew, species, ...) has a natural-language
retrieval query. Instead of feeding the whole document to every extractor, the
pipeline retrieves the chunks most relevant to that extractor's category and
passes only those. Keeping the queries here keeps ``modules.py`` readable and
gives one place to tune retrieval per category.
"""

from __future__ import annotations

from app.rag.vector_store import VectorStore

# One retrieval query per extraction category. Keys mirror the conditional
# extractors in IncidentAnalysisModule._extract_conditionally.
CATEGORY_QUERIES: dict[str, str] = {
    "vessel": (
        "vessel name, flag state, IMO or registration number, call sign, "
        "owner and operator, vessel type and tracking"
    ),
    "crew": (
        "crew members, crew composition and nationality, captain, "
        "recruitment channels, migrant workers"
    ),
    "labor": (
        "labor conditions, working conditions, welfare and safety, wages, "
        "work contracts, forced labor or abuse, inspections"
    ),
    "catch": (
        "fishing dates, locations and areas, fishing gear and methods, "
        "catch certification and authorization"
    ),
    "compliance": (
        "fishing licenses, permits, authorization, regulatory compliance "
        "status, RFMO membership and international agreements"
    ),
    "species": (
        "fish species and marine animals caught, common and scientific names, "
        "quantities and weights"
    ),
    "event": (
        "enforcement event such as seizure, arrest, boarding, inspection, "
        "fine or investigation, with date, location and resolution"
    ),
    "transshipment": (
        "transshipment or transfer of catch between vessels, reefer or carrier "
        "vessel, authorization, dates and locations"
    ),
    "aquaculture": (
        "fish farm or aquaculture operation, farm location, harvest dates, "
        "farming methods, broodstock sources"
    ),
    "trade_distribution": (
        "seafood trade, importer and exporter, buyers, transport, distribution "
        "and landing of product, aggregation and ports"
    ),
    "products": (
        "seafood products, product type and processing, HS code, weight, "
        "destination and labeling"
    ),
    "classification": (
        "illegal, unreported or unregulated fishing activity, labor abuse, "
        "seafood fraud or mislabeling, sanctions, illegal aquaculture"
    ),
    "summary": (
        "who was involved, what violation occurred, when and where it happened, "
        "and what enforcement action was taken"
    ),
}


def query_for_category(category: str) -> str:
    """Return the retrieval query for ``category`` (raises KeyError if unknown)."""
    return CATEGORY_QUERIES[category]


async def retrieve_context(
    store: VectorStore, source_id: str, category: str, k: int = 5
) -> str:
    """Retrieve and concatenate the chunks most relevant to ``category``.

    Returns the joined chunk text (blank-line separated) suitable for passing as
    the ``text`` input to a focused extractor. Empty when nothing is retrieved.
    """
    chunks = await store.retrieve(query_for_category(category), k, source_id=source_id)
    return "\n\n".join(chunk.text for chunk in chunks)
