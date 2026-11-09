"""Unit tests for app/dedup/kde_compare.py (per-KDE duplicate scoring)."""

from types import SimpleNamespace

import pytest

from app.dedup.kde_compare import (
    IDENTIFIER_CONFLICT_CEILING,
    IDENTIFIER_MATCH_FLOOR,
    KDE_CONFLICT_CEILING,
    combine,
    compare_dates,
    compare_equal,
    compare_identifiers,
    compare_locations,
    compare_sets,
    compare_species,
    compare_vessel_names,
    extract_kdes,
    normalize_identifier,
    normalize_vessel_name,
    parse_date,
    score_pair,
)
from app.models.incidents import EventData, Species, VesselData
from tests.conftest import make_classification, make_extracted_data


def fake_incident(id=None, **data_overrides):
    """Duck-typed incident: the code under test only reads attributes, and a
    real IncidentReport requires an initialised Beanie collection."""
    return SimpleNamespace(
        id=id,
        embedding_text_hash=None,
        sources=[],
        extracted_information=make_extracted_data(**data_overrides),
        incident_classification=make_classification(),
    )


@pytest.mark.unit
class TestNormalisation:
    @pytest.mark.parametrize(
        "raw", ["F/V Ocean Star", "MV Ocean Star", "m/v ocean star", "Ocean  Star!"]
    )
    def test_vessel_prefixes_and_punctuation(self, raw):
        assert normalize_vessel_name(raw) == "ocean star"

    def test_identifier_strips_imo_label(self):
        assert normalize_identifier("IMO 9123456") == "9123456"
        assert normalize_identifier("imo-9123456") == "9123456"
        assert normalize_identifier("  ") is None


@pytest.mark.unit
class TestParseDate:
    def test_full_date(self):
        parsed = parse_date("2024-03-02")
        assert parsed.precision == "day"
        assert parsed.start == parsed.end

    def test_month_precision(self):
        parsed = parse_date("March 2024")
        assert parsed.precision == "month"
        assert (parsed.start.day, parsed.end.day) == (1, 31)

    def test_year_precision(self):
        parsed = parse_date("2023")
        assert parsed.precision == "year"

    def test_unparseable(self):
        assert parse_date("sometime last spring") is None
        assert parse_date(None) is None


@pytest.mark.unit
class TestComparers:
    def test_missing_side_is_unknown(self):
        assert compare_vessel_names("Ocean Star", None) is None
        assert compare_equal(None, "Panama") is None
        assert compare_dates("2024-01-01", None) is None
        assert compare_locations([], ["Palk Strait"]) is None
        assert compare_species([], [{"asfis": "COD"}]) is None
        assert compare_sets([], ["Illegal Fishing"]) is None
        assert compare_identifiers({}, {"mmsi": "1"}) is None

    def test_vessel_name_fuzzy(self):
        assert compare_vessel_names("F/V Ocean Star", "Ocean Star") == 1.0
        assert compare_vessel_names("Ocean Star", "Ocean Starr") > 0.9
        assert compare_vessel_names("Ocean Star", "Blue Marlin") < 0.5

    def test_dates(self):
        assert compare_dates("2024-03-02", "2 March 2024") == 1.0
        assert compare_dates("2024-03-02", "2024-03-17") == pytest.approx(0.5)
        assert compare_dates("2024-03-02", "2024-06-01") == 0.0
        # Overlapping but coarse: scaled by the coarser precision.
        assert compare_dates("2024", "2024-03-02") == pytest.approx(0.6)

    def test_identifiers(self):
        assert (
            compare_identifiers({"unique_id": "9123456"}, {"unique_id": "9123456"})
            == 1.0
        )
        assert (
            compare_identifiers({"unique_id": "9123456"}, {"unique_id": "9999999"})
            == 0.0
        )
        # Same value recorded under a different identifier type.
        assert compare_identifiers({"unique_id": "412000"}, {"mmsi": "412000"}) == 1.0

    def test_species_matches_across_key_types(self):
        a = [{"asfis": "COD", "scientific": None, "common": "atlantic cod"}]
        b = [{"asfis": None, "scientific": None, "common": "cod atlantic"}]
        assert compare_species(a, b) == 1.0

        c = [
            {"asfis": "COD", "scientific": None, "common": None},
            {"asfis": "HAD", "scientific": None, "common": None},
        ]
        assert compare_species(a, c) == pytest.approx(0.5)

    def test_sets(self):
        assert compare_sets(["Illegal Fishing"], ["illegal fishing"]) == 1.0
        assert compare_sets(["A", "B"], ["B", "C"]) == pytest.approx(1 / 3)


@pytest.mark.unit
class TestCombine:
    def test_weighted_mean_over_available_signals(self):
        combined, coverage = combine(1.0, {"vessel_name": 0.5})
        # vector 0.30 * 1.0 + vessel_name 0.20 * 0.5 over 0.50 total weight.
        assert combined == pytest.approx(0.8)
        assert coverage == pytest.approx(0.5)

    def test_no_signals(self):
        assert combine(None, {}) == (0.0, 0.0)

    def test_identifier_match_floor(self):
        combined, _ = combine(0.5, {"identifiers": 1.0, "vessel_name": 0.2})
        assert combined == IDENTIFIER_MATCH_FLOOR

    def test_name_conflict_caps_score(self):
        combined, _ = combine(
            0.95, {"vessel_name": 0.2, "species": 1.0, "iuu_types": 1.0}
        )
        assert combined == KDE_CONFLICT_CEILING

    def test_date_conflict_caps_score(self):
        combined, _ = combine(0.95, {"event_date": 0.0, "species": 1.0})
        assert combined == KDE_CONFLICT_CEILING

    def test_identifier_match_beats_name_conflict(self):
        combined, _ = combine(0.9, {"identifiers": 1.0, "vessel_name": 0.1})
        assert combined == IDENTIFIER_MATCH_FLOOR

    def test_identifier_conflict_ceiling(self):
        combined, _ = combine(0.99, {"identifiers": 0.0, "vessel_name": 1.0})
        assert combined == IDENTIFIER_CONFLICT_CEILING


@pytest.mark.unit
class TestScorePair:
    def _incident(self, **kw):
        return fake_incident(**kw)

    def test_same_event_scores_high(self):
        a = self._incident(
            vesselInformation=VesselData(
                vesselName="F/V Ocean Star", vesselFlag="Panama"
            ),
            eventData=EventData(
                eventDate="2024-03-02", eventLocation="Gulf of Mannar", resolution="x"
            ),
            speciesInvolved=[Species(speciesCommonName="Sea cucumber")],
        )
        b = self._incident(
            vesselInformation=VesselData(vesselName="Ocean Star", vesselFlag="panama"),
            eventData=EventData(
                eventDate="March 2, 2024",
                eventLocation="Gulf of Mannar, Sri Lanka",
                resolution="y",
            ),
            speciesInvolved=[Species(speciesCommonName="sea cucumbers")],
        )
        score = score_pair(a, b, vector_score=0.9)
        assert score.kde_scores["vessel_name"] == 1.0
        assert score.kde_scores["event_date"] == 1.0
        assert score.combined > 0.9
        assert score.coverage > 0.9

    def test_different_events_score_low(self):
        a = self._incident(
            vesselInformation=VesselData(vesselName="Ocean Star"),
            eventData=EventData(eventDate="2024-03-02", resolution="x"),
        )
        b = self._incident(
            vesselInformation=VesselData(vesselName="Blue Marlin"),
            eventData=EventData(eventDate="2021-07-19", resolution="y"),
        )
        assert score_pair(a, b, vector_score=0.85).combined <= KDE_CONFLICT_CEILING

    def test_extract_kdes_identifiers(self):
        incident = self._incident(
            vesselInformation=VesselData(vesselUniqueID="IMO 9123456", mmsiNumber="")
        )
        assert extract_kdes(incident).identifiers == {"unique_id": "9123456"}
