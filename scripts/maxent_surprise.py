"""Per-quarter IPF surprisal analysis of Illegal Fishing enforcement.

For each quarter from 2021-Q1 onward (and ``iuu_type == "Illegal Fishing"``),
build the observed country x iuu_subtype contingency table and compare it to
an expected table produced by Iterative Proportional Fitting (IPF) seeded
with the pooled counts from all *prior* quarters (causal / backwards-looking).

Seed (per quarter ``q``, trailing window of ``k`` quarters):
    S_q[c, s] = sum over q' in [q-k, q) of O_{q'}[c, s] + 0.5
                                            (0.5 prior for sparse cells)
``k`` is controlled by ``--prior-quarters``; default is all prior quarters.

IPF then rescales S_q so its row sums equal ``O_q.sum(axis=1)`` and its
column sums equal ``O_q.sum(axis=0)``, yielding the expected table E_q.
This preserves the country-subtype association pattern observed *up to but
not including* the current quarter while matching the current quarter's
marginals. The earliest quarter has no prior history, so its seed reduces
to the uniform 0.5 prior and IPF collapses to the within-quarter
independence model.

Per cell we report:
    - expected: E_q[c, s]
    - z:        (O - E) / sqrt(E)         (Poisson z-score)
    - pmi:      log(O / E)                (where defined)

Cells with the largest |z| are the most "surprising" departures from the
prior-quarters baseline.

Usage:
    python scripts/maxent_surprise.py \\
        --input scripts/data/enforcement_country_quarter_by_iuu.csv \\
        --output-dir scripts/data \\
        --figure-dir scripts/figures\\
        --prior-quarters 4 \\
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyipf import ipf

logger = logging.getLogger(__name__)

MIN_QUARTER = pd.Period("2022Q1", freq="Q")
TARGET_IUU_TYPE = "Illegal Fishing"
NA_SUBTYPE_SENTINEL = "NA"
SEED_PRIOR = 0.5


def load_and_filter(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["quarter"] = pd.PeriodIndex(df["quarter"], freq="Q")
    before = len(df)
    df = df[df["iuu_type"] == TARGET_IUU_TYPE]
    df = df[df["iuu_subtype"] != NA_SUBTYPE_SENTINEL]
    df = df[df["iuu_subtype"].notna()]
    df = df[df["country_code"].notna()]
    logger.info("Filtered %d -> %d rows", before, len(df))
    return df.reset_index(drop=True)


def _quarter_table(
    df: pd.DataFrame, countries: list[str], subtypes: list[str]
) -> np.ndarray:
    """Pivot a per-quarter slice into a dense countries x subtypes matrix."""
    pivot = (
        df.groupby(["country_code", "iuu_subtype"], as_index=False)["count"]
        .sum()
        .pivot(index="country_code", columns="iuu_subtype", values="count")
        .reindex(index=countries, columns=subtypes)
        .fillna(0.0)
    )
    return pivot.to_numpy(dtype=float)


def score_cells_ipf(
    df: pd.DataFrame,
    prior_quarters: int | None = None,
    score_from: pd.Period | None = None,
) -> pd.DataFrame:
    """Score cells via per-quarter IPF.

    ``prior_quarters`` controls the causal seed window:
        - ``None`` (default): use all strictly prior quarters.
        - positive int ``k``: use only the most recent ``k`` prior quarters.
    Quarters with no prior history (or ``prior_quarters == 0``) collapse to
    the uniform 0.5 seed, i.e. within-quarter independence.

    ``score_from`` is the earliest quarter for which records are emitted.
    Quarters before ``score_from`` still populate the ``full`` cube and so
    contribute to later quarters' seeds, but they are not themselves scored.
    Defaults to the earliest quarter present in ``df`` (no skip).
    """
    countries = sorted(df["country_code"].unique())
    subtypes = sorted(df["iuu_subtype"].unique())
    quarters = sorted(df["quarter"].unique())

    full = np.zeros((len(quarters), len(countries), len(subtypes)), dtype=float)
    for qi, q in enumerate(quarters):
        full[qi] = _quarter_table(df[df["quarter"] == q], countries, subtypes)

    records: list[dict] = []
    for qi, q in enumerate(quarters):
        if score_from is not None and q < score_from:
            continue
        Observed = full[qi]
        if Observed.sum() == 0:
            continue

        # Causal seed: pool only the prior-window quarters, plus 0.5 prior
        # on every cell. When the window is empty (qi == 0, or
        # prior_quarters == 0), the seed is uniform 0.5 and IPF collapses
        # to within-quarter independence.
        start = 0 if prior_quarters is None else max(0, qi - prior_quarters)
        seed = full[start:qi].sum(axis=0) + SEED_PRIOR

        row_targets = Observed.sum(axis=1)
        col_targets = Observed.sum(axis=0)

        # Drop countries/subtypes with zero target for this quarter; IPF
        # locks those rows/cols to zero anyway and pyipf's relative-convergence
        # check divides by the target.
        row_keep = row_targets > 0
        col_keep = col_targets > 0
        if not row_keep.any() or not col_keep.any():
            continue

        sub_seed = seed[np.ix_(row_keep, col_keep)]
        sub_row = row_targets[row_keep]
        sub_col = col_targets[col_keep]

        # pyipf marginal order: marginals[k] = target sum over axis k
        # (shape = Z.shape with axis k removed).
        E_sub = ipf(
            sub_seed.copy(),
            [sub_col, sub_row],
            tol_convg=1e-8,
            max_itr=2000,
        )

        E = np.zeros_like(Observed)
        E[np.ix_(row_keep, col_keep)] = E_sub

        for ci, country in enumerate(countries):
            if not row_keep[ci]:
                continue
            for si, subtype in enumerate(subtypes):
                if not col_keep[si]:
                    continue
                o = Observed[ci, si]
                e = E[ci, si]
                if e <= 0:
                    continue
                records.append(
                    {
                        "country_code": country,
                        "quarter": q,
                        "iuu_subtype": subtype,
                        "observed": o,
                        "expected": e,
                        "z": (o - e) / np.sqrt(e),
                        "pmi": np.log(o / e) if o > 0 else float("-inf"),
                    }
                )

    return pd.DataFrame.from_records(records)


def plot_quarter_heatmap(
    quarter: pd.Period, q_cells: pd.DataFrame, out_path: Path, global_vmax: float
) -> None:
    pivot = q_cells.pivot(index="iuu_subtype", columns="country_code", values="z")
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)
    pivot = pivot.loc[pivot.abs().max(axis=1).sort_values(ascending=False).index]

    fig, ax = plt.subplots(
        figsize=(
            max(6.0, 0.35 * pivot.shape[1] + 3),
            max(4.0, 0.3 * pivot.shape[0] + 2),
        )
    )
    im = ax.imshow(
        pivot.to_numpy(),
        aspect="auto",
        cmap="RdBu_r",
        vmin=-global_vmax,
        vmax=global_vmax,
    )
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(pivot.columns, rotation=90, fontsize=8)
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index, fontsize=8)
    ax.set_xlabel("Enforcement country")
    ax.set_ylabel("Illegal Fishing subtype")
    ax.set_title(f"IPF Poisson z-score vs. pooled-history baseline | {quarter}")
    fig.colorbar(im, ax=ax, label="z = (O - E) / sqrt(E)")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("scripts/data/enforcement_country_quarter_by_iuu.csv"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("scripts/data"))
    parser.add_argument("--figure-dir", type=Path, default=Path("scripts/figures"))
    parser.add_argument(
        "--prior-quarters",
        type=int,
        default=None,
        help=(
            "Number of immediately-preceding quarters to pool into the IPF "
            "seed. Default: all prior quarters. Pass e.g. 4 for a one-year "
            "trailing window."
        ),
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level, format="%(asctime)s %(levelname)s %(message)s"
    )

    df = load_and_filter(args.input)
    if df.empty:
        logger.warning("No rows remain after filtering; nothing to score.")
        return

    if args.prior_quarters is not None and args.prior_quarters < 0:
        parser.error("--prior-quarters must be >= 0")

    # Decide how far back to load. `prior_quarters=None` -> keep everything;
    # `prior_quarters=k` -> keep only the k pre-MIN_QUARTER quarters needed to
    # seed MIN_QUARTER itself (anything older would be ignored by the seed
    # window anyway).
    if args.prior_quarters is None:
        load_floor = df["quarter"].min()
    else:
        load_floor = MIN_QUARTER - args.prior_quarters

    earliest_available = df["quarter"].min()
    if load_floor < earliest_available:
        shortfall = (load_floor - earliest_available).n  # negative -> # missing
        logger.warning(
            "Requested seed lookback reaches %s but earliest available data "
            "is %s; first %d quarter(s) of scoring will have shorter "
            "effective priors than requested.",
            load_floor,
            earliest_available,
            -shortfall,
        )

    df = df[df["quarter"] >= load_floor].reset_index(drop=True)

    cells = score_cells_ipf(
        df, prior_quarters=args.prior_quarters, score_from=MIN_QUARTER
    )
    if cells.empty:
        logger.warning("IPF produced no scorable cells.")
        return

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cells_out = args.output_dir / "ipf_surprise_cells.csv"
    cells.reindex(cells["z"].abs().sort_values(ascending=False).index).to_csv(
        cells_out, index=False
    )

    global_vmax = float(np.nanmax(np.abs(cells["z"].to_numpy())))
    per_quarter_dir = args.figure_dir / "ipf_surprise_by_quarter"
    for quarter, q_cells in cells.groupby("quarter"):
        fname = f"ipf_surprise_{quarter}.png".replace(" ", "")
        plot_quarter_heatmap(quarter, q_cells, per_quarter_dir / fname, global_vmax)

    suprising_cells = cells[cells["z"].abs() > 5.0]
    logger.info("Found %d cells with |z| > 5.0", len(suprising_cells))
    logger.info("Top 10 (country, quarter, subtype) by z (positive tail):")
    for _, row in cells.sort_values("z", ascending=False).head(10).iterrows():
        logger.info(
            "  %s | %s | %s :: O=%d E=%.2f z=%.2f pmi=%.2f",
            row["country_code"],
            row["quarter"],
            row["iuu_subtype"],
            int(row["observed"]),
            row["expected"],
            row["z"],
            row["pmi"],
        )
    logger.info("Top 10 (country, quarter, subtype) by z (negative tail):")
    for _, row in cells.sort_values("z", ascending=True).head(10).iterrows():
        logger.info(
            "  %s | %s | %s :: O=%d E=%.2f z=%.2f pmi=%.2f",
            row["country_code"],
            row["quarter"],
            row["iuu_subtype"],
            int(row["observed"]),
            row["expected"],
            row["z"],
            row["pmi"],
        )
    logger.info("Wrote %s and per-quarter heatmaps to %s", cells_out, per_quarter_dir)


if __name__ == "__main__":
    main()
