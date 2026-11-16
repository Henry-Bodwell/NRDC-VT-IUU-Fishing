"""Build the text that represents an incident or overview as a single vector.

Document-level vectors drive cross-document similarity (duplicate detection,
clustering). The text is a fixed, labelled template over the key data elements
(KDEs) plus the free-text description/summary, so two extractions of the same
event produce near-identical text regardless of which article they came from.

Empty fields are omitted entirely: a line like ``Vessel: None`` would pull every
vessel-less incident towards the same region of the embedding space.

Each builder also returns a SHA-256 of the text. It is stored on the document as
``embedding_text_hash`` so re-indexing can skip documents whose embedded text
has not changed.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from app.models.incidents import IncidentReport
    from app.models.overviews import IndustryOverview


def _get(obj: Any, path: str) -> Any:
    """Safely follow a dotted attribute path, returning ``None`` on any gap."""
    for part in path.split("."):
        if obj is None:
            return None
        obj = getattr(obj, part, None)
    return obj


def _clean(value: Any) -> str | None:
    """Return a stripped string, or ``None`` for empty / missing values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique(values: Iterable[str | None]) -> list[str]:
    """Drop empties and case-insensitive duplicates, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = _clean(value)
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            out.append(cleaned)
    return out


def _species_labels(species_list: Iterable[Any] | None) -> list[str]:
    """Render species as ``Common name (Scientific name)`` where available."""
    labels = []
    for species in species_list or []:
        common = _clean(getattr(species, "speciesCommonName", None)) or _clean(
            getattr(species, "aggregateCommonName", None)
        )
        scientific = _clean(getattr(species, "scientificName", None))
        if common and scientific:
            labels.append(f"{common} ({scientific})")
        elif common or scientific:
            labels.append(common or scientific)
    return _unique(labels)


def _render(lines: list[tuple[str, str | list[str] | None]]) -> str:
    """Render ``(label, value)`` pairs, skipping empty values."""
    out = []
    for label, value in lines:
        if isinstance(value, list):
            if value:
                out.append(f"{label}: {', '.join(value)}")
        elif value:
            out.append(f"{label}: {value}")
    return "\n".join(out)


def text_hash(text: str) -> str:
    """SHA-256 hex digest of the embedded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def incident_iuu_types(incident: "IncidentReport") -> list[str]:
    """Top-level IUU classification types for an incident, de-duplicated."""
    classifications = _get(incident, "incident_classification.iuuClassifications")
    return _unique(getattr(c, "IUUType", None) for c in classifications or [])


def incident_embedding_text(incident: "IncidentReport") -> tuple[str, str]:
    """Return ``(text, hash)`` representing an incident for embedding."""
    data = incident.extracted_information

    text = _render(
        [
            ("Incident", _clean(_get(data, "description"))),
            ("IUU types", incident_iuu_types(incident)),
            ("Vessel", _clean(_get(data, "vesselInformation.vesselName"))),
            ("Flag", _clean(_get(data, "vesselInformation.vesselFlag"))),
            ("Date", _clean(_get(data, "eventData.eventDate"))),
            (
                "Location",
                _unique(
                    [
                        _get(data, "eventData.eventLocation"),
                        _get(data, "catchInformation.catchArea"),
                    ]
                ),
            ),
            (
                "Country",
                _unique(
                    [
                        _get(data, "eventData.eventCountry"),
                        _get(data, "catchInformation.catchCountry"),
                    ]
                ),
            ),
            (
                "Enforcement",
                _unique(
                    [
                        _get(data, "eventData.enforcementLocation"),
                        _get(data, "eventData.enforcementCountry"),
                    ]
                ),
            ),
            ("Species", _species_labels(_get(data, "speciesInvolved"))),
        ]
    )
    return text, text_hash(text)


def overview_embedding_text(overview: "IndustryOverview") -> tuple[str, str]:
    """Return ``(text, hash)`` representing an industry overview for embedding."""
    data = overview.extracted_information

    text = _render(
        [
            ("Overview", _clean(_get(data, "summary"))),
            ("Species", _species_labels(_get(data, "species"))),
            ("Countries", _unique(_get(data, "countries") or [])),
            ("Companies", _unique(_get(data, "companies") or [])),
        ]
    )
    return text, text_hash(text)
