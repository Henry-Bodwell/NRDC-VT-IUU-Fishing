"""Precision / recall / F1 per KDE group from hand-graded slot-judgment counts.

`scripts/model_metrics.py` buckets every (incident, field) slot into
correct / correct_empty / missing / spurious / mismatch via `classify_change`,
which compares with a raw `==`. That over-reports `mismatch`: case differences,
date formats, list reordering and human rewording of free-text fields all score
as total misses, and a mismatch counts as both a false positive and a false
negative. The counts consumed here have had their mismatches manually reviewed,
so the surviving mismatches are genuine value errors.

Scoring, per group:

    FP = spurious + mismatch
    FN = missing  + mismatch
    TP = correct                    (strict)
    TP = correct + correct_empty    (lenient)

Two variants are reported side by side:

  * strict  -- `correct_empty` excluded as a true negative. Standard
    slot-filling scoring; this is the figure to cite.
  * lenient -- `correct_empty` folded into TP, reproducing the behaviour of
    `kde_rates` so existing runs in scripts/baseline_runs/ stay comparable.

Groups with no ground-truth content at all (gold_support == 0) report n/a in
both variants and are excluded from the macro averages -- otherwise a group the
model never populated scores a meaningless 1.0 under the lenient variant. They
still contribute their counts to the micro totals.

Usage:
    python scripts/kde_group_metrics.py \
        --csv ../iuuMisc/data/kde_mismatch_by_group.csv \
        --json scripts/data/kde_group_metrics.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_lib import _macro_avg, _prf_raw, _safe_div  # noqa: E402

BUCKETS = ("correct", "mismatch", "missing", "spurious", "correct_empty")
VARIANTS = ("strict", "lenient")

DEFAULT_CSV = (
    Path(__file__).resolve().parents[2]
    / "iuuMisc"
    / "data"
    / "kde_mismatch_by_group.csv"
)

# Short labels for the LaTeX table. Groups absent here fall back to a
# de-camelCased form of the raw key, so a new KDE group degrades gracefully.
DISPLAY_NAMES = {
    "aggregationInformation": "Aggregation",
    "aquacultureInformation": "Aquaculture",
    "catchInformation": "Catch",
    "chainOfCustody": "Chain of Custody",
    "complianceInformation": "Compliance",
    "crewInformation": "Crew",
    "distributionInformation": "Distribution",
    "eventData": "Event",
    "laborStandards": "Labor Standards",
    "landingInformation": "Landing",
    "productsInvolved": "Products",
    "sanitaryLicenseID": "Sanitary License",
    "speciesInvolved": "Species",
    "tradeInformation": "Trade",
    "transshipmentInformation": "Transshipment",
    "vesselInformation": "Vessel",
}


# ── Loading ────────────────────────────────────────────────────────────────


def _to_int(raw: str | None, group: str, column: str) -> int:
    """Parse a bucket cell. Blank means zero; anything non-numeric is an error."""
    text = (raw or "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError as exc:
        raise ValueError(
            f"{group!r}: column {column!r} is not numeric ({text!r})"
        ) from exc


def load_group_counts(path: Path) -> list[tuple[str, dict[str, int]]]:
    """Read the hand-graded CSV into (group_name, bucket_counts) pairs."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path} is empty")
        missing_cols = {"kde_group", *BUCKETS} - set(reader.fieldnames)
        if missing_cols:
            raise ValueError(
                f"{path} is missing required column(s): "
                f"{', '.join(sorted(missing_cols))}"
            )
        rows = []
        for row in reader:
            group = (row.get("kde_group") or "").strip()
            if not group:
                continue
            rows.append((group, {b: _to_int(row.get(b), group, b) for b in BUCKETS}))
    if not rows:
        raise ValueError(f"{path} contains no data rows")
    return rows


# ── Scoring ────────────────────────────────────────────────────────────────


def _variant_tp(group: dict, variant: str) -> int:
    """True positives for a group under the given TP rule."""
    if variant == "lenient":
        return group["correct"] + group["correct_empty"]
    return group["correct"]


def score_group(counts: dict[str, int]) -> dict:
    """Score one group's bucket counts under both the strict and lenient TP rules."""
    correct = counts["correct"]
    missing = counts["missing"]
    spurious = counts["spurious"]
    mismatch = counts["mismatch"]

    gold_support = correct + mismatch + missing
    n_predicted = correct + mismatch + spurious
    fp = spurious + mismatch
    fn = missing + mismatch
    scored = gold_support > 0

    out: dict = {
        **counts,
        "gold_support": gold_support,
        "n_predicted": n_predicted,
        "fp": fp,
        "fn": fn,
        "mismatch_rate": (
            round(_safe_div(mismatch, correct + mismatch), 4)
            if correct + mismatch
            else None
        ),
        "scored": scored,
    }
    for variant in VARIANTS:
        if not scored:
            out[variant] = None
            continue
        tp = _variant_tp(out, variant)
        precision, recall, f1 = _prf_raw(tp, fp, fn)
        out[variant] = {
            "tp": tp,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return out


def summarize(scored_groups: dict[str, dict]) -> dict:
    """Micro totals over every group, macro averages over scored groups only."""
    totals = {b: sum(g[b] for g in scored_groups.values()) for b in BUCKETS}
    fp = totals["spurious"] + totals["mismatch"]
    fn = totals["missing"] + totals["mismatch"]

    micro: dict[str, dict] = {}
    macro: dict[str, dict] = {}
    for variant in VARIANTS:
        tp = _variant_tp(totals, variant)
        precision, recall, f1 = _prf_raw(tp, fp, fn)
        micro[variant] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
        # _macro_avg keeps classes with support > 0, which is exactly our gate,
        # and expects unrounded P/R/F1 -- so recompute rather than reuse the
        # rounded per-group blocks.
        macro[variant] = _macro_avg(
            {
                name: (
                    *_prf_raw(
                        _variant_tp(g, variant),
                        g["spurious"] + g["mismatch"],
                        g["missing"] + g["mismatch"],
                    ),
                    g["gold_support"],
                )
                for name, g in scored_groups.items()
                if g["scored"]
            }
        )
    return {"totals": totals, "micro": micro, "macro": macro}


# ── Reporting ──────────────────────────────────────────────────────────────


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _variant_cells(group: dict, variant: str) -> list[str]:
    block = group[variant]
    if block is None:
        return ["n/a", "n/a", "n/a"]
    return [_fmt(block[k]) for k in ("precision", "recall", "f1")]


def print_report(scored_groups: dict[str, dict], aggregates: dict) -> None:
    names = list(scored_groups)
    width = max([len(n) for n in names] + [len("group")]) + 2

    print("\n=== Slot-judgment counts ===")
    print(
        f"  {'group':<{width}}{'correct':>9}{'mismatch':>10}{'missing':>9}"
        f"{'spurious':>10}{'corr_empty':>12}{'mismatch%':>11}"
    )
    for name in names:
        g = scored_groups[name]
        rate = "n/a" if g["mismatch_rate"] is None else f"{g['mismatch_rate']:.4f}"
        print(
            f"  {name:<{width}}{g['correct']:>9}{g['mismatch']:>10}{g['missing']:>9}"
            f"{g['spurious']:>10}{g['correct_empty']:>12}{rate:>11}"
        )

    print("\n=== Precision / recall / F1 ===")
    print("  strict: correct_empty excluded (TN).  lenient: correct_empty as TP.")
    print(
        f"  {'group':<{width}}{'support':>8}{'sP':>9}{'sR':>9}{'sF1':>9}"
        f"{'lP':>9}{'lR':>9}{'lF1':>9}"
    )
    for name in names:
        g = scored_groups[name]
        cells = _variant_cells(g, "strict") + _variant_cells(g, "lenient")
        print(
            f"  {name:<{width}}{g['gold_support']:>8}"
            + "".join(f"{c:>9}" for c in cells)
        )

    n_scored = sum(1 for g in scored_groups.values() if g["scored"])
    n_gated = len(scored_groups) - n_scored
    print(f"\n  {n_scored} group(s) scored, {n_gated} with no ground truth (n/a).")

    print("\n=== Aggregates ===")
    for variant in VARIANTS:
        m = aggregates["micro"][variant]
        print(
            f"  micro {variant:<8} P={m['precision']:.4f} R={m['recall']:.4f} "
            f"F1={m['f1']:.4f}   (tp={m['tp']} fp={m['fp']} fn={m['fn']})"
        )
    for variant in VARIANTS:
        m = aggregates["macro"][variant]
        print(
            f"  macro {variant:<8} P={m['precision']:.4f} R={m['recall']:.4f} "
            f"F1={m['f1']:.4f}   (n_groups={m['n_classes']})"
        )


# ── LaTeX ──────────────────────────────────────────────────────────────────


def _latex_escape(text: str) -> str:
    for char in ("\\", "&", "%", "$", "#", "_", "{", "}"):
        text = text.replace(char, f"\\{char}")
    return text


def _display_name(group: str) -> str:
    """Short table label for a KDE group key."""
    if group in DISPLAY_NAMES:
        return DISPLAY_NAMES[group]
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", group).split()
    trimmed = [w for w in words if w.lower() not in ("information", "data")]
    return " ".join(w.capitalize() for w in (trimmed or words))


def _cells(block: dict | None, decimals: int) -> list[str]:
    """P/R/F1 cells for one variant; an em dash when the group is unscored."""
    if block is None:
        return ["--"] * 3
    return [f"{block[k]:.{decimals}f}" for k in ("precision", "recall", "f1")]


def format_latex(
    scored_groups: dict[str, dict],
    aggregates: dict,
    variant: str = "strict",
    decimals: int = 2,
    include_gated: bool = False,
    include_aggregates: bool = True,
) -> str:
    """Render a booktabs table. `variant` is "strict", "lenient" or "both"."""
    variants = VARIANTS if variant == "both" else (variant,)
    rows = [
        (name, g) for name, g in scored_groups.items() if include_gated or g["scored"]
    ]
    if not rows:
        raise ValueError("no groups to render")

    labels = [_latex_escape(_display_name(name)) for name, _ in rows]
    if include_aggregates:
        labels += ["Micro average", "Macro average"]
    width = max(len(x) for x in labels)

    body = []
    for (_, g), label in zip(rows, labels):
        cells = [c for v in variants for c in _cells(g[v], decimals)]
        body.append(f"        {label:<{width}} & " + " & ".join(cells) + r"\\")

    if include_aggregates:
        body.append(r"        \midrule")
        for agg, label in (("micro", "Micro average"), ("macro", "Macro average")):
            cells = [c for v in variants for c in _cells(aggregates[agg][v], decimals)]
            body.append(f"        {label:<{width}} & " + " & ".join(cells) + r"\\")

    n_metric_cols = 3 * len(variants)
    header = [f"        {'KDE Group':<{width}} & Precision & Recall & F1\\\\"]
    if variant == "both":
        header = [
            f"        {'KDE Group':<{width}} & \\multicolumn{{3}}{{c}}{{Strict}} "
            f"& \\multicolumn{{3}}{{c}}{{Lenient}}\\\\",
            r"        \cmidrule(lr){2-4} \cmidrule(lr){5-7}",
            f"        {'':<{width}} & P & R & F1 & P & R & F1\\\\",
        ]

    return "\n".join(
        [
            r"\begin{table}[t]",
            r"    \footnotesize",
            r"    \setlength{\tabcolsep}{3pt}",
            r"    \centering",
            r"    \caption{Extraction Metrics.}",
            r"    \label{tab:Extraction accuracy}",
            f"    \\begin{{tabular}}{{l{'c' * n_metric_cols}}}",
            r"        \toprule",
            *header,
            r"        \midrule",
            *body,
            r"        \bottomrule",
            r"    \end{tabular}",
            r"\end{table}",
            "",
        ]
    )


def write_latex(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(scored_groups: dict[str, dict], aggregates: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"per_group": scored_groups, **aggregates}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_csv(scored_groups: dict[str, dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "kde_group",
        *BUCKETS,
        "gold_support",
        "n_predicted",
        "mismatch_rate",
        *[f"{v}_{m}" for v in VARIANTS for m in ("precision", "recall", "f1")],
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for name, g in scored_groups.items():
            row = {"kde_group": name}
            row.update({k: g[k] for k in (*BUCKETS, "gold_support", "n_predicted")})
            row["mismatch_rate"] = (
                "" if g["mismatch_rate"] is None else g["mismatch_rate"]
            )
            for variant in VARIANTS:
                block = g[variant]
                for metric in ("precision", "recall", "f1"):
                    row[f"{variant}_{metric}"] = "" if block is None else block[metric]
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Hand-graded per-group counts CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument("--json", type=Path, help="Optional path for the JSON report")
    parser.add_argument(
        "--csv-out", type=Path, help="Optional path for the flat per-group CSV"
    )
    parser.add_argument(
        "--latex",
        type=str,
        metavar="PATH",
        help='Write a booktabs LaTeX table ("-" for stdout)',
    )
    parser.add_argument(
        "--latex-variant",
        choices=(*VARIANTS, "both"),
        default="strict",
        help="Which scoring variant the LaTeX table reports (default: strict)",
    )
    parser.add_argument(
        "--latex-include-gated",
        action="store_true",
        help="Keep zero-ground-truth groups in the LaTeX table, shown as --",
    )
    parser.add_argument(
        "--no-latex-aggregates",
        action="store_true",
        help="Omit the micro/macro average rows from the LaTeX table",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        parser.error(f"CSV not found: {args.csv}")

    rows = load_group_counts(args.csv)
    scored_groups = {name: score_group(counts) for name, counts in rows}
    aggregates = summarize(scored_groups)

    print(f"Source: {args.csv}")
    print_report(scored_groups, aggregates)

    if args.json:
        write_json(scored_groups, aggregates, args.json)
        print(f"\nWrote JSON to {args.json}")
    if args.csv_out:
        write_csv(scored_groups, args.csv_out)
        print(f"Wrote CSV to {args.csv_out}")
    if args.latex:
        table = format_latex(
            scored_groups,
            aggregates,
            variant=args.latex_variant,
            include_gated=args.latex_include_gated,
            include_aggregates=not args.no_latex_aggregates,
        )
        if args.latex == "-":
            print(f"\n=== LaTeX ({args.latex_variant}) ===\n")
            print(table)
        else:
            write_latex(table, Path(args.latex))
            print(f"Wrote LaTeX to {args.latex}")


if __name__ == "__main__":
    main()
