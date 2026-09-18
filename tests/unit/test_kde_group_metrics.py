"""
Unit tests for scripts/kde_group_metrics.py.

Covers the metric primitives shared with model_metrics.py, the strict vs
lenient TP rules, the zero-support gate, and CSV parsing of blank cells.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _review_lib import _prf_raw  # noqa: E402
from kde_group_metrics import (  # noqa: E402
    _display_name,
    format_latex,
    load_group_counts,
    score_group,
    summarize,
)

# The hand-graded counts from ../iuuMisc/data/kde_mismatch_by_group.csv.
FIXTURE_ROWS = [
    ("aggregationInformation", 0, 0, 0, 1, 163),
    ("aquacultureInformation", 12, 0, 0, 4, 523),
    ("catchInformation", 25, 2, 5, 4, 366),
    ("chainOfCustody", 0, 0, 0, 0, 53),
    ("complianceInformation", 9, 0, 0, 0, 488),
    ("crewInformation", 18, 1, 4, 2, 312),
    ("distributionInformation", 2, 0, 2, 0, 245),
    ("eventData", 268, 16, 23, 12, 130),
    ("laborStandards", 47, 6, 2, 4, 468),
    ("landingInformation", 4, 0, 0, 0, 200),
    ("productsInvolved", 15, 3, 7, 1, 27),
    ("sanitaryLicenseID", 0, 0, 0, 0, 53),
    ("speciesInvolved", 11, 4, 4, 1, 33),
    ("tradeInformation", 7, 1, 3, 1, 192),
    ("transshipmentInformation", 8, 0, 1, 1, 382),
    ("vesselInformation", 25, 0, 4, 2, 474),
]

CSV_HEADER = "kde_group,correct,mismatch,missing,spurious,correct_empty,mismatch_rate"


def counts(correct, mismatch, missing, spurious, correct_empty):
    return {
        "correct": correct,
        "mismatch": mismatch,
        "missing": missing,
        "spurious": spurious,
        "correct_empty": correct_empty,
    }


@pytest.fixture
def fixture_csv(tmp_path):
    """The full hand-graded CSV, with mismatch_rate left blank as in the real file."""
    lines = [CSV_HEADER]
    lines += [
        f"{name},{c},{mm},{mi},{sp},{ce}," for name, c, mm, mi, sp, ce in FIXTURE_ROWS
    ]
    path = tmp_path / "kde_mismatch_by_group.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def scored(fixture_csv):
    rows = load_group_counts(fixture_csv)
    return {name: score_group(c) for name, c in rows}


@pytest.fixture
def aggregates_fixture(scored):
    return summarize(scored)


@pytest.mark.unit
class TestPrfRaw:
    """The shared primitive relocated into _review_lib."""

    def test_hand_worked_case(self):
        # tp=6, fp=2, fn=3 -> P=0.75, R=0.6666..., F1=0.7058...
        precision, recall, f1 = _prf_raw(6, 2, 3)
        assert precision == pytest.approx(0.75)
        assert recall == pytest.approx(2 / 3)
        assert f1 == pytest.approx(0.70588235, abs=1e-6)

    def test_all_zero_is_zero_not_zero_division(self):
        assert _prf_raw(0, 0, 0) == (0.0, 0.0, 0.0)

    def test_perfect_score(self):
        assert _prf_raw(10, 0, 0) == (1.0, 1.0, 1.0)


@pytest.mark.unit
class TestScoreGroup:
    """Strict vs lenient TP rules and the zero-support gate."""

    def test_event_data_strict(self):
        g = score_group(counts(268, 16, 23, 12, 130))
        # TP=268, FP=16+12=28, FN=16+23=39
        assert g["fp"] == 28
        assert g["fn"] == 39
        assert g["gold_support"] == 307
        assert g["strict"] == {
            "tp": 268,
            "precision": 0.9054,
            "recall": 0.873,
            "f1": 0.8889,
        }

    def test_event_data_lenient_folds_correct_empty_into_tp(self):
        g = score_group(counts(268, 16, 23, 12, 130))
        assert g["lenient"]["tp"] == 398
        assert g["lenient"]["precision"] == 0.9343
        assert g["lenient"]["recall"] == 0.9108

    def test_mismatch_counts_as_both_fp_and_fn(self):
        g = score_group(counts(10, 5, 0, 0, 0))
        assert g["fp"] == 5
        assert g["fn"] == 5

    def test_zero_support_gates_both_variants(self):
        # chainOfCustody: nothing populated on either side.
        g = score_group(counts(0, 0, 0, 0, 53))
        assert g["scored"] is False
        assert g["strict"] is None
        assert g["lenient"] is None, "lenient must not report 1.0 off pure TNs"

    def test_lone_spurious_is_still_gated(self):
        # aggregationInformation: one false positive, no ground truth at all.
        g = score_group(counts(0, 0, 0, 1, 163))
        assert g["gold_support"] == 0
        assert g["scored"] is False
        assert g["strict"] is None
        assert g["lenient"] is None

    def test_mismatch_rate_is_none_when_nothing_populated_on_both_sides(self):
        assert score_group(counts(0, 0, 0, 0, 53))["mismatch_rate"] is None
        assert score_group(counts(268, 16, 23, 12, 130))["mismatch_rate"] == 0.0563


@pytest.mark.unit
class TestLoadGroupCounts:
    """CSV parsing, including the blank cells present in the real file."""

    def test_blank_mismatch_rate_does_not_raise(self, fixture_csv):
        rows = load_group_counts(fixture_csv)
        assert len(rows) == len(FIXTURE_ROWS)
        assert dict(rows)["chainOfCustody"]["correct_empty"] == 53

    def test_blank_bucket_cell_reads_as_zero(self, tmp_path):
        path = tmp_path / "blanks.csv"
        path.write_text(f"{CSV_HEADER}\neventData,268,,23,12,130,\n", encoding="utf-8")
        assert dict(load_group_counts(path))["eventData"]["mismatch"] == 0

    def test_missing_column_is_reported(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text("kde_group,correct,mismatch\neventData,1,2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required column"):
            load_group_counts(path)

    def test_non_numeric_cell_names_the_row(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text(f"{CSV_HEADER}\neventData,lots,0,0,0,0,\n", encoding="utf-8")
        with pytest.raises(ValueError, match="eventData"):
            load_group_counts(path)

    def test_empty_file_is_reported(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text(f"{CSV_HEADER}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no data rows"):
            load_group_counts(path)


@pytest.mark.unit
class TestSummarize:
    """Micro totals span every group; macro averages only the scored ones."""

    def test_micro_totals(self, scored):
        micro = summarize(scored)["micro"]["strict"]
        assert (micro["tp"], micro["fp"], micro["fn"]) == (451, 66, 88)
        assert micro["precision"] == 0.8723
        assert micro["recall"] == 0.8367
        assert micro["f1"] == 0.8542

    def test_micro_lenient_tp_includes_every_correct_empty(self, scored):
        assert summarize(scored)["micro"]["lenient"]["tp"] == 4560

    def test_gated_groups_excluded_from_macro(self, scored):
        macro = summarize(scored)["macro"]
        assert macro["strict"]["n_classes"] == 13
        assert macro["lenient"]["n_classes"] == 13

    def test_macro_averages_unrounded_values(self, scored):
        # Averaging the rounded per-group figures would give 0.8626 here.
        assert summarize(scored)["macro"]["strict"]["precision"] == 0.8625

    def test_gated_groups_still_contribute_to_micro(self, scored):
        # aggregationInformation's lone spurious is a real false positive.
        assert scored["aggregationInformation"]["scored"] is False
        assert summarize(scored)["totals"]["spurious"] == 33


@pytest.mark.unit
class TestDisplayName:
    """Table labels for KDE group keys."""

    def test_known_group(self):
        assert _display_name("eventData") == "Event"
        assert _display_name("laborStandards") == "Labor Standards"

    def test_unknown_group_falls_back_to_decamelcased(self):
        assert _display_name("bycatchInformation") == "Bycatch"
        assert _display_name("newThingData") == "New Thing"

    def test_unknown_group_of_only_stripped_words_keeps_them(self):
        assert _display_name("information") == "Information"


@pytest.mark.unit
class TestFormatLatex:
    """Booktabs table rendering."""

    def test_structure(self, scored, aggregates_fixture):
        table = format_latex(scored, aggregates_fixture)
        assert table.startswith("\\begin{table}[t]")
        assert table.rstrip().endswith("\\end{table}")
        # Column spec must match the number of metric columns actually emitted.
        assert "\\begin{tabular}{lccc}" in table
        for rule in ("\\toprule", "\\midrule", "\\bottomrule"):
            assert rule in table

    def test_gated_groups_dropped_by_default(self, scored, aggregates_fixture):
        table = format_latex(scored, aggregates_fixture)
        assert "Chain of Custody" not in table
        assert "Aggregation" not in table
        assert "Event" in table

    def test_gated_groups_render_as_dashes_when_included(
        self, scored, aggregates_fixture
    ):
        table = format_latex(scored, aggregates_fixture, include_gated=True)
        assert "Chain of Custody & -- & -- & --" in table

    def test_values_rounded_to_two_decimals(self, scored, aggregates_fixture):
        table = format_latex(scored, aggregates_fixture)
        assert "Event           & 0.91 & 0.87 & 0.89" in table

    def test_aggregate_rows(self, scored, aggregates_fixture):
        table = format_latex(scored, aggregates_fixture)
        assert "Micro average   & 0.87 & 0.84 & 0.85" in table
        assert "Macro average   & 0.86 & 0.80 & 0.82" in table

    def test_aggregates_can_be_omitted(self, scored, aggregates_fixture):
        table = format_latex(scored, aggregates_fixture, include_aggregates=False)
        assert "Micro average" not in table

    def test_lenient_variant_uses_lenient_numbers(self, scored, aggregates_fixture):
        table = format_latex(scored, aggregates_fixture, variant="lenient")
        assert "Event           & 0.93 & 0.91 & 0.92" in table

    def test_both_variant_widens_the_column_spec(self, scored, aggregates_fixture):
        table = format_latex(scored, aggregates_fixture, variant="both")
        assert "\\begin{tabular}{lcccccc}" in table
        assert "\\cmidrule(lr){2-4} \\cmidrule(lr){5-7}" in table
        assert "Event           & 0.91 & 0.87 & 0.89 & 0.93 & 0.91 & 0.92" in table

    def test_special_characters_escaped(self, aggregates_fixture):
        groups = {"a_b&c": score_group(counts(5, 0, 1, 0, 0))}
        table = format_latex(groups, aggregates_fixture, include_aggregates=False)
        assert "A\\_b\\&c" in table

    def test_empty_selection_raises(self, aggregates_fixture):
        groups = {"chainOfCustody": score_group(counts(0, 0, 0, 0, 53))}
        with pytest.raises(ValueError, match="no groups to render"):
            format_latex(groups, aggregates_fixture)
