"""Keep document-level vectors in sync with incidents and overviews.

Every function here is best-effort: a Qdrant or embedding failure is logged and
swallowed so that saving an incident never fails because the similarity index
is unavailable. A backfill (``scripts/backfill_document_vectors.py``) repairs
anything missed.

``embedding_text_hash`` is written with a raw ``$set`` rather than
``document.save()`` so that bookkeeping does not create audit-log entries or
bump the document version.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterable

from app.rag.document_text import incident_embedding_text, overview_embedding_text
from app.rag.vector_store import (
    DOC_TYPE_INCIDENT,
    DOC_TYPE_OVERVIEW,
    get_document_store,
)

if TYPE_CHECKING:
    from app.models.incidents import IncidentReport
    from app.models.overviews import IndustryOverview

logger = logging.getLogger(__name__)


async def _store_hash(document, text_hash: str) -> None:
    """Persist ``embedding_text_hash`` without triggering audit hooks."""
    await type(document).find_one(type(document).id == document.id).update(
        {"$set": {"embedding_text_hash": text_hash}}
    )
    document.embedding_text_hash = text_hash


async def index_incidents(
    incidents: Iterable["IncidentReport"], *, force: bool = False
) -> int:
    """Embed incidents whose embedded text changed; returns the number indexed."""
    try:
        return await _index_incidents(incidents, force=force)
    except Exception as e:
        logger.warning(f"Document vector indexing failed for incidents: {e}")
        return 0


async def _index_incidents(incidents: Iterable["IncidentReport"], force: bool) -> int:
    pending = []
    for incident in incidents:
        if incident.id is None:
            continue
        text, text_hash = incident_embedding_text(incident)
        if not text or (not force and incident.embedding_text_hash == text_hash):
            continue
        event_data = incident.extracted_information.eventData
        event_date = event_data.eventDate if event_data else None
        pending.append((incident, text, text_hash, {"event_date": event_date or None}))

    if not pending:
        return 0

    await get_document_store().upsert_documents(
        [(DOC_TYPE_INCIDENT, str(i.id), t, extra) for i, t, _, extra in pending]
    )
    for incident, _, text_hash, _ in pending:
        await _store_hash(incident, text_hash)
    return len(pending)


async def index_incident(incident: "IncidentReport", *, force: bool = False) -> bool:
    """Embed a single incident; returns True if a vector was written."""
    return await index_incidents([incident], force=force) == 1


async def index_overview(overview: "IndustryOverview", *, force: bool = False) -> bool:
    """Embed an industry overview; returns True if a vector was written."""
    try:
        if overview.id is None:
            return False
        text, text_hash = overview_embedding_text(overview)
        if not text or (not force and overview.embedding_text_hash == text_hash):
            return False
        await get_document_store().upsert_documents(
            [(DOC_TYPE_OVERVIEW, str(overview.id), text, {})]
        )
        await _store_hash(overview, text_hash)
    except Exception as e:
        logger.warning(
            f"Document vector indexing failed for overview "
            f"{getattr(overview, 'id', None)}: {e}"
        )
        return False
    return True


async def remove_document(doc_type: str, doc_id: str) -> None:
    """Delete a document's vector; failures are logged, never raised."""
    try:
        await get_document_store().delete_document(doc_type, doc_id)
    except Exception as e:
        logger.warning(f"Could not delete document vector {doc_type}:{doc_id}: {e}")
