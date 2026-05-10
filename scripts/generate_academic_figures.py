"""Generate academic figures from IncidentReport stats endpoints.

Pulls aggregated counts from the running API and renders PNG figures:

  1. incidents_by_country.png        - world choropleth
  2. incidents_by_year.png           - bar chart by year
  3. incidents_by_iuu_type.png       - bar chart by IUU type
  4. iuu_subtypes_by_class.png       - per-class subtype bars (faceted)
  5. kde_field_rates.png             - per-field non-null rate
  6. kde_fill_rate_distribution.png  - per-incident fill rate histogram
  7. iuu_cooccurrence.png            - type co-occurrence heatmap

Usage:
    python scripts/generate_academic_figures.py \
        --base-url http://localhost:8000 \
        --output-dir scripts/figures
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)


IUU_TYPES_ORDER = [
    "Illegal Fishing",
    "Unreported Catch",
    "Unregulated Fishing",
    "Seafood Fraud or Mislabeling",
    "Forced Labor or Labor Abuse",
    "Circumventing Prohibitions or Sanctions",
    "Illegal Aquacultural Practices",
    "Other",
]


KDE_FIELD_EXCLUDE = {"description", "sanitaryLicenseID", "chainOfCustody"}


NATURAL_EARTH_ISO3_OVERRIDES = {
    "France": "FRA",
    "Norway": "NOR",
    "Kosovo": "XKX",
    "N. Cyprus": "CYP",
    "Somaliland": "SOM",
}


async def fetch_all(base_url: str, auth_token: str | None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
    endpoints = {
        "countries": "/api/incidents/stats/event-countries",
        "years": "/api/incidents/stats/years",
        "iuu_types": "/api/incidents/stats/iuu-types",
        "iuu_subtypes": "/api/incidents/stats/iuu-subtypes",
        "cooccurrence": "/api/incidents/stats/iuu-cooccurrence",
        "subtype_cooccurrence": "/api/incidents/stats/iuu-subtype-cooccurrence",
        "kde_fields": "/api/incidents/stats/KDEDistribution",
        "kde_fill": "/api/incidents/stats/KDEFillRate",
    }
    async with httpx.AsyncClient(
        base_url=base_url, timeout=60.0, headers=headers
    ) as client:

        async def get(name: str, path: str) -> tuple[str, Any]:
            r = await client.get(path)
            r.raise_for_status()
            return name, r.json()

        results = await asyncio.gather(
            *(get(name, path) for name, path in endpoints.items())
        )
    return dict(results)


def plot_country_map(rows: list[dict], out: Path) -> None:
    """World choropleth of incident counts by ISO3 eventCountry."""
    try:
        import geopandas as gpd
    except ImportError:
        logger.warning("geopandas not installed; falling back to bar chart")
        _plot_country_bar(rows, out)
        return

    counts = {r["country_code"]: r["count"] for r in rows}
    try:
        world = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres"))
    except Exception:
        ne_url = (
            "https://naciscdn.org/naturalearth/110m/cultural/"
            "ne_110m_admin_0_countries.zip"
        )
        world = gpd.read_file(ne_url)

    iso_col = "iso_a3" if "iso_a3" in world.columns else "ISO_A3"
    name_col = "name" if "name" in world.columns else "NAME"
    world[iso_col] = world.apply(
        lambda r: NATURAL_EARTH_ISO3_OVERRIDES.get(r[name_col], r[iso_col]),
        axis=1,
    )
    world["count"] = world[iso_col].map(counts).fillna(0).astype(int)

    fig, ax = plt.subplots(figsize=(14, 7))
    plot_counts = world["count"].replace(0, np.nan)
    world.plot(
        column=plot_counts,
        ax=ax,
        legend=True,
        cmap="YlOrRd",
        missing_kwds={"color": "lightgrey", "label": "No incidents"},
        legend_kwds={
            "label": "Incident count (eventCountry)",
            "orientation": "horizontal",
            "shrink": 0.6,
        },
        edgecolor="white",
        linewidth=0.3,
    )
    ax.set_axis_off()
    ax.set_title("Incident Distribution by Country", fontsize=14)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _plot_country_bar(rows: list[dict], out: Path, top_n: int = 25) -> None:
    rows = sorted(rows, key=lambda r: r["count"], reverse=True)[:top_n]
    labels = [r["country_code"] for r in rows]
    counts = [r["count"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, max(4, len(rows) * 0.3)))
    ax.barh(labels[::-1], counts[::-1], color="steelblue")
    ax.set_xlabel("Incident count")
    ax.set_title(f"Top {top_n} Countries by Incident Count")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def plot_years(rows: list[dict], out: Path) -> None:
    rows = sorted(rows, key=lambda r: r["year"])
    years = [r["year"] for r in rows]
    counts = [r["count"] for r in rows]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(years, counts, color="steelblue")
    ax.set_xlabel("Year")
    ax.set_ylabel("Incident count")
    ax.set_title("Incident Distribution by Year")
    for label in ax.get_xticklabels():
        label.set_rotation(45)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def plot_iuu_types(rows: list[dict], out: Path) -> None:
    rows = sorted(rows, key=lambda r: r["count"], reverse=True)
    labels = [r["iuu_type"] for r in rows]
    counts = [r["count"] for r in rows]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(labels[::-1], counts[::-1], color="steelblue")
    ax.set_xlabel("Incident count")
    ax.set_title("Incident Distribution by IUU Classification")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def plot_subtypes_by_class(rows: list[dict], out: Path) -> None:
    by_type: dict[str, list[tuple[str, int]]] = {}
    for r in rows:
        by_type.setdefault(r["iuu_type"], []).append((r["subtype"], r["count"]))

    types_present = [t for t in IUU_TYPES_ORDER if t in by_type]
    n = len(types_present)
    if n == 0:
        logger.warning("No subtype data to plot")
        return

    fig, axes = plt.subplots(
        nrows=n, ncols=1, figsize=(10, max(3, 2.2 * n)), constrained_layout=True
    )
    if n == 1:
        axes = [axes]
    for ax, iuu_type in zip(axes, types_present):
        items = sorted(by_type[iuu_type], key=lambda x: x[1])
        labels = [s for s, _ in items]
        counts = [c for _, c in items]
        ax.barh(labels, counts, color="steelblue")
        ax.set_title(iuu_type, fontsize=11, loc="left")
        ax.set_xlabel("Count")
    fig.suptitle("IUU Subtype Prevalence by Class", fontsize=14)
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_kde_field_rates(payload: dict, out: Path) -> None:
    fields = payload.get("fields", {})
    if not fields:
        logger.warning("No KDE field data to plot")
        return
    fields = {k: v for k, v in fields.items() if k not in KDE_FIELD_EXCLUDE}
    items = sorted(fields.items(), key=lambda kv: kv[1]["non_null_rate"])
    labels = [k for k, _ in items]
    rates = [v["non_null_rate"] for _, v in items]
    fig, ax = plt.subplots(figsize=(9, max(4, len(labels) * 0.3)))
    ax.barh(labels, rates, color="steelblue")
    ax.set_xlabel("Non-null rate")
    ax.set_xlim(0, 1)
    ax.set_title(f"KDE Field Non-Null Rates (n={payload.get('total', 0)} incidents)")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def plot_kde_fill_distribution(payload: dict, out: Path) -> None:
    rates = payload.get("rates", [])
    total_fields = payload.get("total_fields", 0)
    if not rates:
        logger.warning("No KDE fill-rate data to plot")
        return
    arr = np.asarray(rates, dtype=float)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(arr, bins=20, range=(0, 1), color="steelblue", edgecolor="white")
    mean = float(arr.mean())
    median = float(np.median(arr))
    ax.axvline(mean, color="darkred", linestyle="--", label=f"Mean = {mean:.2f}")
    ax.axvline(median, color="darkgreen", linestyle=":", label=f"Median = {median:.2f}")
    ax.set_xlabel(f"Per-incident KDE fill rate (of {total_fields} fields)")
    ax.set_ylabel("Number of incidents")
    ax.set_title("Distribution of KDE Fill Rate per Incident")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def _render_cooccurrence_heatmap(
    labels: list[str],
    pairs: list[dict],
    title: str,
    out: Path,
    figsize: tuple[float, float] | None = None,
    label_fontsize: int = 8,
) -> None:
    from matplotlib.colors import LogNorm

    idx = {t: i for i, t in enumerate(labels)}
    n = len(labels)
    mat = np.zeros((n, n), dtype=int)
    for p in pairs:
        a, b = p.get("a"), p.get("b")
        if a in idx and b in idx:
            mat[idx[a]][idx[b]] = p["count"]

    if figsize is None:
        side = max(6.0, 0.5 * n + 4.0)
        figsize = (side + 2.0, side)
    fig, ax = plt.subplots(figsize=figsize)
    nonzero = mat[mat > 0]
    vmin = int(nonzero.min()) if nonzero.size else 1
    vmax = int(mat.max()) if mat.max() > 0 else 1
    masked = np.ma.masked_where(mat == 0, mat)
    cmap = plt.get_cmap("YlOrRd").copy()
    cmap.set_bad(color="whitesmoke")
    im = ax.imshow(masked, cmap=cmap, norm=LogNorm(vmin=vmin, vmax=max(vmax, vmin + 1)))
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=label_fontsize)
    ax.set_yticklabels(labels, fontsize=label_fontsize)
    log_max = np.log10(max(vmax, vmin + 1))
    log_min = np.log10(vmin)
    log_threshold = log_min + 0.6 * (log_max - log_min)
    for i in range(n):
        for j in range(n):
            val = mat[i][j]
            if val:
                color = "white" if np.log10(val) > log_threshold else "black"
                ax.text(
                    j,
                    i,
                    str(val),
                    ha="center",
                    va="center",
                    color=color,
                    fontsize=max(6, label_fontsize - 1),
                )
    ax.set_title(title)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Incident count (log)")
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _slug(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def plot_subtype_cooccurrence_per_type(by_type: dict, out_dir: Path) -> None:
    """One heatmap per IUU type over its subtypes."""
    if not by_type:
        logger.warning("No subtype co-occurrence data to plot")
        return
    for iuu_type, pairs in by_type.items():
        if not pairs:
            continue
        labels = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
        out = out_dir / f"subtype_cooccurrence_{_slug(iuu_type)}.png"
        _render_cooccurrence_heatmap(
            labels=labels,
            pairs=pairs,
            title=f"{iuu_type}: Subtype Co-occurrence (log scale)",
            out=out,
            label_fontsize=8,
        )


def plot_cooccurrence(pairs: list[dict], out: Path) -> None:
    types = IUU_TYPES_ORDER
    idx = {t: i for i, t in enumerate(types)}
    n = len(types)
    mat = np.zeros((n, n), dtype=int)
    for p in pairs:
        a, b = p.get("a"), p.get("b")
        if a in idx and b in idx:
            mat[idx[a]][idx[b]] = p["count"]

    from matplotlib.colors import LogNorm

    fig, ax = plt.subplots(figsize=(10, 9))
    nonzero = mat[mat > 0]
    vmin = int(nonzero.min()) if nonzero.size else 1
    vmax = int(mat.max()) if mat.max() > 0 else 1
    masked = np.ma.masked_where(mat == 0, mat)
    cmap = plt.get_cmap("YlOrRd").copy()
    cmap.set_bad(color="whitesmoke")
    im = ax.imshow(masked, cmap=cmap, norm=LogNorm(vmin=vmin, vmax=max(vmax, vmin + 1)))
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(types, rotation=45, ha="right")
    ax.set_yticklabels(types)
    log_max = np.log10(max(vmax, vmin + 1))
    log_min = np.log10(vmin)
    log_threshold = log_min + 0.6 * (log_max - log_min)
    for i in range(n):
        for j in range(n):
            val = mat[i][j]
            if val:
                color = "white" if np.log10(val) > log_threshold else "black"
                ax.text(
                    j,
                    i,
                    str(val),
                    ha="center",
                    va="center",
                    color=color,
                    fontsize=8,
                )
    ax.set_title(
        "IUU Type Co-occurrence (log scale; diagonal = incidents containing that type)"
    )
    fig.colorbar(im, ax=ax, shrink=0.7, label="Incident count (log)")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


async def main_async(args: argparse.Namespace) -> None:
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Fetching stats from %s", args.base_url)
    data = await fetch_all(args.base_url, args.auth_token)

    plot_country_map(data["countries"]["counts"], out_dir / "incidents_by_country.png")
    plot_years(data["years"]["counts"], out_dir / "incidents_by_year.png")
    plot_iuu_types(data["iuu_types"]["counts"], out_dir / "incidents_by_iuu_type.png")
    plot_subtypes_by_class(
        data["iuu_subtypes"]["counts"], out_dir / "iuu_subtypes_by_class.png"
    )
    plot_kde_field_rates(data["kde_fields"], out_dir / "kde_field_rates.png")
    plot_kde_fill_distribution(
        data["kde_fill"], out_dir / "kde_fill_rate_distribution.png"
    )
    plot_cooccurrence(data["cooccurrence"]["pairs"], out_dir / "iuu_cooccurrence.png")
    plot_subtype_cooccurrence_per_type(data["subtype_cooccurrence"]["by_type"], out_dir)

    logger.info("Wrote figures to %s", out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("AUTH_TOKEN"),
        help="Bearer token. Stats endpoints are public, but accepted as fallback.",
    )
    parser.add_argument("--output-dir", default="scripts/figures")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
