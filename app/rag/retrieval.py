"""Category-scoped retrieval for the extraction pipeline.

Each focused DSPy extractor (vessel, crew, species, ...) has a natural-language
retrieval query. Instead of feeding the whole document to every extractor, the
pipeline retrieves the chunks most relevant to that extractor's category and
passes only those. Keeping the queries here keeps ``modules.py`` readable and
gives one place to tune retrieval per category.

These queries are static, so their embeddings are cached process-wide by the
vector store -- see ``VectorStore._embed_query``.
"""

from __future__ import annotations

from app.rag.chunking import Chunk
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


def compose_query(category: str, extra_query: str | None = None) -> str:
    """Build the retrieval query for ``category``, optionally narrowed.

    ``extra_query`` scopes the category query to a specific subject -- used by
    the multi-incident path so each incident's extractors retrieve chunks about
    *that* incident rather than the document as a whole.
    """
    base = query_for_category(category)
    if not extra_query:
        return base
    return f"{extra_query}\n{base}"


async def retrieve_chunks(
    store: VectorStore,
    source_id: str,
    category: str,
    k: int = 5,
    *,
    extra_query: str | None = None,
) -> list[Chunk]:
    """Retrieve the chunks most relevant to ``category`` for a source.

    Returns the :class:`Chunk` objects themselves, each carrying its similarity
    ``score``, so callers can log or gate on relevance. Use :func:`join_chunks`
    to turn them into extractor input. Empty when nothing is retrieved.
    """
    return await store.retrieve(
        compose_query(category, extra_query), k, source_id=source_id
    )


def join_chunks(chunks: list[Chunk]) -> str:
    """Join retrieved chunks into a single extractor input string."""
    return "\n\n".join(chunk.text for chunk in chunks)
