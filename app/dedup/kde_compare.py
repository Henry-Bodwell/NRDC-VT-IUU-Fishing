"""Field-by-field (KDE) comparison of two incidents for duplicate detection.

Each comparer returns a score in ``[0, 1]``, or ``None`` when either incident is
missing the field. Missing data is *unknown*, never a mismatch: extractions
from different articles routinely fill different subsets of fields.

The per-field scores are combined with the document-vector cosine similarity
into a single ``combined`` score via a weighted mean over the fields both
incidents have (see :data:`WEIGHTS`). Hard vessel identifiers (IMO / MMSI /
call sign / unique ID) override that mean: a shared identifier is strong
evidence of the same vessel, a conflicting one is strong evidence against.

Everything tunable lives in the module-level constants so thresholds and
weights can be adjusted while experimenting; bump :data:`SCORING_VERSION` when
they change so stored candidates record which scheme produced them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from dateutil import parser as date_parser
from rapidfuzz import fuzz

from app.rag.document_text import incident_iuu_types

if TYPE_CHECKING:
    from app.models.incidents import IncidentReport

SCORING_VERSION = "kde-v1"

# Relative weight of each signal in the combined score. Only signals present on
# both incidents participate; the weights are renormalised over those.
WEIGHTS: dict[str, float] = {
    "vector": 0.30,
    "vessel_name": 0.20,
    "event_date": 0.15,
    "location": 0.10,
    "species": 0.10,
    "country": 0.05,
    "vessel_flag": 0.05,
    "iuu_types": 0.05,
}

# Identifier overrides applied after the weighted mean.
IDENTIFIER_MATCH_FLOOR = 0.90
IDENTIFIER_CONFLICT_CEILING = 0.30

# Strong-evidence fields: when both incidents have the field and its score is
# below the threshold, the combined score is capped at KDE_CONFLICT_CEILING.
# Without this, weak shared signals (a common species, the same IUU type) plus
# a high vector score can lift clearly different events into review range.
KDE_CONFLICT_THRESHOLDS: dict[str, float] = {
    "vessel_name": 0.5,
    "event_date": 0.01,
}
KDE_CONFLICT_CEILING = 0.50

# Dates further apart than this score 0.
DATE_WINDOW_DAYS = 30

# Date scores are scaled by the coarser of the two dates' precision, so two
# "2023" dates overlapping is weaker evidence than two identical days.
DATE_PRECISION_FACTOR = {"day": 1.0, "month": 0.85, "year": 0.6}

# Two species names are treated as the same when their fuzzy ratio reaches this.
SPECIES_NAME_MATCH = 90

_VESSEL_PREFIX = re.compile(
    r"^(?:f\s*/\s*v|m\s*/\s*v|m\s*/\s*t|m\s*/\s*s|f\s*/\s*b|fv|mv|mt|ms|fb|km|kmn)"
    r"\.?\s+",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_IMO_PREFIX = re.compile(r"^imo", re.IGNORECASE)


# ── Normalisation ──────────────────────────────────────────────────


def _get(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if obj is None:
            return None
        obj = getattr(obj, part, None)
    return obj


def normalize_text(value: str | None) -> str | None:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    if value is None:
        return None
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = " ".join(_NON_ALNUM.sub(" ", text).split())
    return text or None


def normalize_vessel_name(value: str | None) -> str | None:
    """Normalise a vessel name, dropping type prefixes such as F/V or MV."""
    if value is None:
        return None
    stripped = _VESSEL_PREFIX.sub("", str(value).strip())
    return normalize_text(stripped)


def normalize_identifier(value: str | None) -> str | None:
    """Uppercase alphanumerics only, without a leading ``IMO`` label."""
    if value is None:
        return None
    text = _IMO_PREFIX.sub("", str(value).strip())
    text = re.sub(r"[^0-9A-Za-z]", "", text).upper()
    return text or None


@dataclass(frozen=True)
class DateRange:
    """A parsed date with its precision, as an inclusive day range."""

    start: date
    end: date
    precision: str  # "day" | "month" | "year"


def parse_date(value: str | None) -> DateRange | None:
    """Parse a free-text date into a range reflecting its precision.

    ``dateutil`` fills missing components from a default date. Parsing twice
    with two different defaults reveals which components were actually
    present: any component that differs between the two parses was filled in.
    """
    if not value or not str(value).strip():
        return None
    text = str(value)
    try:
        first = date_parser.parse(text, default=datetime(1904, 1, 1), fuzzy=True)
        second = date_parser.parse(text, default=datetime(1908, 2, 2), fuzzy=True)
    except (ValueError, OverflowError, TypeError):
        return None

    if first.year != second.year:
        return None
    if first.month != second.month:
        return DateRange(date(first.year, 1, 1), date(first.year, 12, 31), "year")
    if first.day != second.day:
        start = date(first.year, first.month, 1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return DateRange(start, next_month - timedelta(days=1), "month")
    return DateRange(first.date(), first.date(), "day")


# ── Extracted KDEs ─────────────────────────────────────────────────


@dataclass
class IncidentKDEs:
    """The comparable key data elements of one incident."""

    vessel_name: str | None = None
    vessel_flag: str | None = None
    identifiers: dict[str, str] = field(default_factory=dict)
    event_date: str | None = None
    locations: list[str] = field(default_factory=list)
    country: str | None = None
    species: list[dict[str, str | None]] = field(default_factory=list)
    iuu_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def extract_kdes(incident: "IncidentReport") -> IncidentKDEs:
    """Pull the comparable KDEs out of an incident."""
    data = incident.extracted_information
    vessel = _get(data, "vesselInformation")

    identifiers = {}
    for key, path in (
        ("unique_id", "vesselUniqueID"),
        ("mmsi", "mmsiNumber"),
        ("call_sign", "internationalRadioCallSign"),
    ):
        normalized = normalize_identifier(_get(vessel, path))
        if normalized:
            identifiers[key] = normalized

    locations = [
        loc
        for loc in (
            _get(data, "eventData.eventLocation"),
            _get(data, "catchInformation.catchArea"),
        )
        if loc and str(loc).strip()
    ]

    species = []
    for sp in _get(data, "speciesInvolved") or []:
        entry = {
            "asfis": normalize_identifier(getattr(sp, "ASFISCode", None)),
            "scientific": normalize_text(getattr(sp, "scientificName", None)),
            "common": normalize_text(
                getattr(sp, "speciesCommonName", None)
                or getattr(sp, "aggregateCommonName", None)
            ),
        }
        if any(entry.values()):
            species.append(entry)

    return IncidentKDEs(
        vessel_name=_get(vessel, "vesselName"),
        vessel_flag=_get(vessel, "vesselFlag"),
        identifiers=identifiers,
        event_date=_get(data, "eventData.eventDate"),
        locations=locations,
        country=_get(data, "eventData.eventCountry")
        or _get(data, "catchInformation.catchCountry"),
        species=species,
        iuu_types=incident_iuu_types(incident),
    )


# ── Comparers ──────────────────────────────────────────────────────


def compare_identifiers(a: dict[str, str], b: dict[str, str]) -> float | None:
    """1.0 if any identifier matches, 0.0 if shared ones all conflict, else None."""
    shared = set(a) & set(b)
    if not shared:
        # A unique ID on one side may be an MMSI or call sign on the other.
        if set(a.values()) & set(b.values()):
            return 1.0
        return None
    if any(a[k] == b[k] for k in shared) or set(a.values()) & set(b.values()):
        return 1.0
    return 0.0


def compare_vessel_names(a: str | None, b: str | None) -> float | None:
    na, nb = normalize_vessel_name(a), normalize_vessel_name(b)
    if not na or not nb:
        return None
    return fuzz.ratio(na, nb) / 100.0


def compare_equal(a: str | None, b: str | None) -> float | None:
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return None
    return 1.0 if na == nb else 0.0


def compare_dates(a: str | None, b: str | None) -> float | None:
    ra, rb = parse_date(a), parse_date(b)
    if ra is None or rb is None:
        return None
    gap = max(0, (rb.start - ra.end).days, (ra.start - rb.end).days)
    proximity = max(0.0, 1.0 - gap / DATE_WINDOW_DAYS)
    precision = min(
        DATE_PRECISION_FACTOR[ra.precision], DATE_PRECISION_FACTOR[rb.precision]
    )
    return proximity * precision


def compare_locations(a: list[str], b: list[str]) -> float | None:
    na = [n for n in (normalize_text(x) for x in a) if n]
    nb = [n for n in (normalize_text(x) for x in b) if n]
    if not na or not nb:
        return None
    return max(fuzz.token_set_ratio(x, y) for x in na for y in nb) / 100.0


def _same_species(x: dict, y: dict) -> bool:
    if x["asfis"] and y["asfis"]:
        return x["asfis"] == y["asfis"]
    if x["scientific"] and y["scientific"]:
        return x["scientific"] == y["scientific"]
    if x["common"] and y["common"]:
        return fuzz.token_set_ratio(x["common"], y["common"]) >= SPECIES_NAME_MATCH
    return False


def compare_species(a: list[dict], b: list[dict]) -> float | None:
    """Jaccard overlap, matching on ASFIS code, then scientific, then common name."""
    if not a or not b:
        return None
    matched_b: set[int] = set()
    overlap = 0
    for x in a:
        for j, y in enumerate(b):
            if j not in matched_b and _same_species(x, y):
                matched_b.add(j)
                overlap += 1
                break
    return overlap / (len(a) + len(b) - overlap)


def compare_sets(a: list[str], b: list[str]) -> float | None:
    sa = {normalize_text(x) for x in a} - {None}
    sb = {normalize_text(x) for x in b} - {None}
    if not sa or not sb:
        return None
    return len(sa & sb) / len(sa | sb)


# ── Combination ────────────────────────────────────────────────────


@dataclass
class PairScore:
    """Result of comparing two incidents."""

    vector_score: float | None
    kde_scores: dict[str, float | None]
    combined: float
    coverage: float  # share of total weight that had data on both sides


def score_kdes(a: IncidentKDEs, b: IncidentKDEs) -> dict[str, float | None]:
    """Per-field scores for two incidents' KDEs."""
    return {
        "identifiers": compare_identifiers(a.identifiers, b.identifiers),
        "vessel_name": compare_vessel_names(a.vessel_name, b.vessel_name),
        "vessel_flag": compare_equal(a.vessel_flag, b.vessel_flag),
        "event_date": compare_dates(a.event_date, b.event_date),
        "location": compare_locations(a.locations, b.locations),
        "country": compare_equal(a.country, b.country),
        "species": compare_species(a.species, b.species),
        "iuu_types": compare_sets(a.iuu_types, b.iuu_types),
    }


def combine(
    vector_score: float | None, kde_scores: dict[str, float | None]
) -> tuple[float, float]:
    """Return ``(combined, coverage)`` for a set of signal scores."""
    signals = {**kde_scores, "vector": vector_score}
    total_weight = sum(WEIGHTS.values())
    available = {
        name: score
        for name, score in signals.items()
        if name in WEIGHTS and score is not None
    }
    used_weight = sum(WEIGHTS[name] for name in available)
    if used_weight == 0:
        combined = 0.0
    else:
        combined = (
            sum(WEIGHTS[name] * score for name, score in available.items())
            / used_weight
        )

    if any(
        kde_scores.get(name) is not None and kde_scores[name] < threshold
        for name, threshold in KDE_CONFLICT_THRESHOLDS.items()
    ):
        combined = min(combined, KDE_CONFLICT_CEILING)

    # Identifiers are applied last so a shared IMO/MMSI outweighs a name or
    # date conflict (vessels get renamed; dates get misreported).
    identifiers = kde_scores.get("identifiers")
    if identifiers == 1.0:
        combined = max(combined, IDENTIFIER_MATCH_FLOOR)
    elif identifiers == 0.0:
        combined = min(combined, IDENTIFIER_CONFLICT_CEILING)

    return round(combined, 4), round(used_weight / total_weight, 4)


def score_pair(
    a: "IncidentReport", b: "IncidentReport", vector_score: float | None
) -> PairScore:
    """Compare two incidents and combine with their vector similarity."""
    kde_scores = score_kdes(extract_kdes(a), extract_kdes(b))
    combined, coverage = combine(vector_score, kde_scores)
    return PairScore(
        vector_score=vector_score,
        kde_scores=kde_scores,
        combined=combined,
        coverage=coverage,
    )
