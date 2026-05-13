"""Maximum-entropy surprisal analysis of Illegal Fishing enforcement.

Applies the principle of maximum entropy to the 3-way contingency table
(country x quarter x iuu_subtype) for rows where ``iuu_type == "Illegal
Fishing"`` from 2020-Q1 onward, then ranks cells by how strongly they
deviate from the max-entropy baseline.

The max-entropy distribution constrained only by the three one-dimensional
marginals is the product of marginals (independence model):

    p_hat(c, q, s) = p(c) * p(q) * p(s)
    E_hat(c, q, s) = N * p_hat(c, q, s)

For each observed cell with count O we report:
    - expected:        E_hat
    - pmi:             log(O / E_hat)
    - pearson:         (O - E_hat) / sqrt(E_hat)
    - surprisal_bits:  -log2(p_hat)

This is NOT a Phillips-style MaxEnt species distribution model; it is the
principle of maximum entropy applied to a contingency table. Cells with
O = 0 are not enumerated, so the ranking surfaces "surprisingly frequent"
rather than "surprisingly absent" combinations.

Usage:
    python scripts/maxent_surprise.py \\
        --input scripts/data/enforcement_country_quarter_by_iuu.csv \\
        --output-dir scripts/data \\
        --figure-dir scripts/figures
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_QUARTER = pd.Period("2022Q1", freq="Q")
TARGET_IUU_TYPE = "Illegal Fishing"
NA_SUBTYPE_SENTINEL = "NA"


def load_and_filter(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["quarter"] = pd.PeriodIndex(df["quarter"], freq="Q")
    before = len(df)
    df = df[df["quarter"] >= MIN_QUARTER]
    df = df[df["iuu_type"] == TARGET_IUU_TYPE]
    df = df[df["iuu_subtype"] != NA_SUBTYPE_SENTINEL]
    df = df[df["country_code"].notna()]
    logger.info("Filtered %d -> %d rows", before, len(df))
    return df.reset_index(drop=True)


def score_cells(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    cells = (
        df.groupby(["country_code", "quarter", "iuu_subtype"], as_index=False)["count"]
        .sum()
        .rename(columns={"count": "observed"})
    )
    n = float(cells["observed"].sum())

    p_country = cells.groupby("country_code")["observed"].sum() / n
    p_quarter = cells.groupby("quarter")["observed"].sum() / n
    p_subtype = cells.groupby("iuu_subtype")["observed"].sum() / n

    cells["p_hat"] = (
        cells["country_code"].map(p_country)
        * cells["quarter"].map(p_quarter)
        * cells["iuu_subtype"].map(p_subtype)
    )
    cells["expected"] = n * cells["p_hat"]
    cells["pmi"] = np.log(cells["observed"] / cells["expected"])
    cells["pearson"] = (cells["observed"] - cells["expected"]) / np.sqrt(
        cells["expected"]
    )
    cells["surprisal_bits"] = -np.log2(cells["p_hat"])

    p_emp = cells["observed"].to_numpy() / n
    h_empirical = float(-np.sum(p_emp * np.log2(p_emp)))
    p_hat = cells["p_hat"].to_numpy()
    h_baseline = float(-np.sum(p_emp * np.log2(p_hat)))
    diagnostics = {
        "N": n,
        "n_cells_observed": float(len(cells)),
        "H_empirical_bits": h_empirical,
        "H_baseline_cross_entropy_bits": h_baseline,
        "KL_empirical_to_baseline_bits": h_baseline - h_empirical,
    }
    return cells, diagnostics


def plot_quarter_heatmap(
    quarter: pd.Period, q_cells: pd.DataFrame, out_path: Path, global_vmax: float
) -> None:
    pivot = q_cells.pivot(index="iuu_subtype", columns="country_code", values="pearson")
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
    ax.set_title(f"Pearson residual vs. max-entropy baseline | {quarter}")
    fig.colorbar(im, ax=ax, label="Pearson residual")
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

    cells, diagnostics = score_cells(df)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cells_out = args.output_dir / "maxent_surprise_cells.csv"
    cells.sort_values("pearson", ascending=False).to_csv(cells_out, index=False)

    global_vmax = float(np.nanmax(np.abs(cells["pearson"].to_numpy())))
    per_quarter_dir = args.figure_dir / "maxent_surprise_by_quarter"
    for quarter, q_cells in cells.groupby("quarter"):
        fname = f"maxent_surprise_{quarter}.png".replace(" ", "")
        plot_quarter_heatmap(quarter, q_cells, per_quarter_dir / fname, global_vmax)

    logger.info("Diagnostics: %s", diagnostics)
    logger.info("Top 10 (country, quarter, subtype) by Pearson residual:")
    top = cells.sort_values("pearson", ascending=False).head(10)
    for _, row in top.iterrows():
        logger.info(
            "  %s | %s | %s :: O=%d E=%.2f pearson=%.2f pmi=%.2f",
            row["country_code"],
            row["quarter"],
            row["iuu_subtype"],
            int(row["observed"]),
            row["expected"],
            row["pearson"],
            row["pmi"],
        )
    logger.info("Wrote %s and per-quarter heatmaps to %s", cells_out, per_quarter_dir)


if __name__ == "__main__":
    main()
