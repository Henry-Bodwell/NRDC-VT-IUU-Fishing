"""Map/reduce incident segmentation for multi-incident documents.

The legacy approach asked the LLM to emit, for every incident, a copy of the
full article as ``full_context`` -- which blows the output-token ceiling on long
papers. This module instead:

1. **Map**: over each chunk, extract short *incident anchors* (vessel name,
   named actor, date, location, event type). Output is tiny per chunk.
2. **Reduce**: consolidate the aggregated anchors into a deduplicated list of
   :class:`IncidentDescriptor`, each a short descriptor plus a retrieval query.

Downstream, each descriptor's ``retrieval_query`` fetches the relevant chunks
(scoped to the source) so the per-incident extractors never carry the whole
document.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.rag.chunking import Chunk


class IncidentDescriptor(BaseModel):
    """A distinct incident discovered in a multi-incident document."""

    description: str = Field(
        description="Short description of this incident (who/what/where/when)."
    )
    anchors: list[str] = Field(
        default_factory=list,
        description="Distinguishing identifiers that pin this incident.",
    )
    retrieval_query: str = Field(
        description="Query used to fetch the chunks supporting this incident."
    )


def _default_mapper():
    """Build the default per-chunk anchor mapper (deferred import breaks cycle)."""
    import dspy
    from app.dspy_files.signatures import IdentifyIncidentAnchors

    return dspy.ChainOfThought(IdentifyIncidentAnchors)


def _default_reducer():
    """Build the default anchor consolidator (deferred import breaks cycle)."""
    import dspy
    from app.dspy_files.signatures import ConsolidateIncidents

    return dspy.ChainOfThought(ConsolidateIncidents)


async def segment_incidents(
    chunks: list[Chunk], *, mapper=None, reducer=None
) -> list[IncidentDescriptor]:
    """Discover distinct incidents across a document's chunks.

    Args:
        chunks: The document's chunks.
        mapper: DSPy module whose ``acall(text=...)`` yields ``.anchors`` per
            chunk. Defaults to a ``IdentifyIncidentAnchors`` ChainOfThought.
        reducer: DSPy module whose ``acall(anchors=...)`` yields ``.incidents``.
            Defaults to a ``ConsolidateIncidents`` ChainOfThought.

    Returns:
        The consolidated list of :class:`IncidentDescriptor`. Empty input yields
        an empty list without invoking the reducer.
    """
    if not chunks:
        return []

    if mapper is None:
        mapper = _default_mapper()
    if reducer is None:
        reducer = _default_reducer()

    aggregated_anchors: list[str] = []
    for chunk in chunks:
        result = await mapper.acall(text=chunk.text)
        anchors = getattr(result, "anchors", None) or []
        aggregated_anchors.extend(anchors)

    reduced = await reducer.acall(anchors=aggregated_anchors)
    return list(getattr(reduced, "incidents", []) or [])
