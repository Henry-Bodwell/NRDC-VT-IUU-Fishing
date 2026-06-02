"""Compare KDE-leaf fill rates across ground truth, v1 pipeline, and two
baseline LM extractions (4o-mini, 5.4-mini).

Restricted to the same source IDs used for the baseline runs
(scripts/data/ids.csv, ~103 sources). For each source we follow its linked
incidents and pull:
  - Ground truth: current incident state (the reviewed DB state)
  - v1: GET /api/logs/{incident_id}/version/1

4o-mini and 5.4-mini fill data come from the offline baseline metric JSON
files (counts: ``correct + mismatch + spurious`` per leaf).

Renders two PNGs:

  1. kde_leaf_fill_rates_by_source.png  - per-leaf grouped horizontal bars
  2. kde_leaf_filled_total_by_source.png - mean populated leaves per incident
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _review_lib import extract_link_id, load_ids  # noqa: E402

logger = logging.getLogger(__name__)


KDE_FIELD_EXCLUDE = {"description", "sanitaryLicenseID", "chainOfCustody"}


def _is_excluded(path: str, exclude: set[str]) -> bool:
    if path in exclude:
        return True
    return any(path.startswith(f"{e}.") for e in exclude)


def _is_populated(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def _walk(state: dict | None, path: str) -> Any:
    cur: Any = state or {}
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _filled_count(entry: dict[str, Any]) -> int:
    return entry.get("correct", 0) + entry.get("mismatch", 0) + entry.get("spurious", 0)


def load_metrics_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = json.load(f)
    kde_leaf = data["metrics"]["kde_leaf"]
    n_incidents = data["counts"]["incidents_processed"]

    rates: dict[str, float] = {}
    total_filled = 0
    for leaf, entry in kde_leaf.items():
        if "." not in leaf:
            continue
        n_j = entry.get("n_judgments", 0)
        filled = _filled_count(entry)
        total_filled += filled
        if n_j > 0:
            rates[leaf] = filled / n_j

    return {
        "rates": rates,
        "filled_per_incident": (total_filled / n_incidents) if n_incidents else 0.0,
        "incidents": n_incidents,
    }


async def _get_json(client: httpx.AsyncClient, path: str) -> dict | None:
    try:
        r = await client.get(path)
    except httpx.HTTPError as e:
        logger.warning("GET %s failed: %s", path, e)
        return None
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        logger.warning("GET %s -> %d", path, r.status_code)
        return None
    return r.json()


async def fetch_api_sources(
    base_url: str,
    auth_token: str | None,
    ids_file: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pull ground truth + v1 state for incidents linked to ids_file sources."""
    source_ids = load_ids(ids_file)
    logger.info("Loaded %d source IDs from %s", len(source_ids), ids_file)

    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"), headers=headers, timeout=120.0
    ) as client:
        lp = await _get_json(client, "/api/incidents/stats/leaf-presence")
        if not lp:
            raise RuntimeError("Could not fetch /api/incidents/stats/leaf-presence")
        all_leaf_paths: list[str] = lp["leaf_paths"]
        kept_paths = [
            p for p in all_leaf_paths if not _is_excluded(p, KDE_FIELD_EXCLUDE)
        ]
        logger.info(
            "Schema has %d leaves, %d after exclusions",
            len(all_leaf_paths),
            len(kept_paths),
        )

        sem = asyncio.Semaphore(8)

        async def get_source(sid: str) -> dict | None:
            async with sem:
                return await _get_json(client, f"/api/sources/{sid}")

        logger.info("Fetching %d sources", len(source_ids))
        sources = await asyncio.gather(*(get_source(sid) for sid in source_ids))

        incident_ids: list[str] = []
        seen: set[str] = set()
        missing_sources = 0
        for src in sources:
            if not src:
                missing_sources += 1
                continue
            for link in src.get("incidents") or []:
                iid = extract_link_id(link)
                if iid and iid not in seen:
                    seen.add(iid)
                    incident_ids.append(iid)
        logger.info(
            "Resolved %d unique incidents (sources missing: %d)",
            len(incident_ids),
            missing_sources,
        )

        async def get_incident(iid: str) -> tuple[str, dict | None, dict | None]:
            async with sem:
                curr = await _get_json(client, f"/api/incidents/{iid}")
                v1_log = await _get_json(client, f"/api/logs/{iid}/version/1")
                v1_state = v1_log.get("state") if isinstance(v1_log, dict) else None
                return iid, curr, v1_state

        results = await asyncio.gather(*(get_incident(iid) for iid in incident_ids))

    gt_filled_counts = {p: 0 for p in kept_paths}
    v1_filled_counts = {p: 0 for p in kept_paths}
    gt_total = v1_total = 0
    gt_n = v1_n = 0

    for iid, curr, v1_state in results:
        if curr:
            gt_n += 1
            extracted = (
                curr.get("extracted_information") if isinstance(curr, dict) else None
            )
            for p in kept_paths:
                if _is_populated(_walk(extracted, p)):
                    gt_filled_counts[p] += 1
                    gt_total += 1
        if v1_state:
            v1_n += 1
            extracted = (
                v1_state.get("extracted_information")
                if isinstance(v1_state, dict)
                else None
            )
            for p in kept_paths:
                if _is_populated(_walk(extracted, p)):
                    v1_filled_counts[p] += 1
                    v1_total += 1

    gt = {
        "rates": {p: gt_filled_counts[p] / gt_n for p in kept_paths} if gt_n else {},
        "filled_per_incident": (gt_total / gt_n) if gt_n else 0.0,
        "incidents": gt_n,
    }
    v1 = {
        "rates": {p: v1_filled_counts[p] / v1_n for p in kept_paths} if v1_n else {},
        "filled_per_incident": (v1_total / v1_n) if v1_n else 0.0,
        "incidents": v1_n,
    }
    logger.info("Ground truth: %d incidents, %d filled leaves", gt_n, gt_total)
    logger.info("v1: %d incidents with state, %d filled leaves", v1_n, v1_total)
    return gt, v1


def plot_per_leaf_fill_rates(
    sources: list[tuple[str, dict[str, Any], str]], out: Path
) -> None:
    leaves: set[str] = set()
    for _, src, _ in sources:
        leaves.update(src["rates"].keys())
    leaves = {
        leaf
        for leaf in leaves
        if "." in leaf and not _is_excluded(leaf, KDE_FIELD_EXCLUDE)
    }

    gt_rates = sources[0][1]["rates"]
    ordered = sorted(leaves, key=lambda leaf: gt_rates.get(leaf, 0.0))

    n = len(ordered)
    if n == 0:
        logger.warning("No leaves to plot")
        return

    fig, ax = plt.subplots(figsize=(11, max(8, 0.25 * n)))
    y = np.arange(n)
    n_src = len(sources)
    bar_h = 0.8 / n_src
    offsets = (np.arange(n_src) - (n_src - 1) / 2.0) * bar_h

    for i, (label, src, color) in enumerate(sources):
        values = [src["rates"].get(leaf, 0.0) for leaf in ordered]
        ax.barh(y + offsets[i], values, height=bar_h, label=label, color=color)

    ax.set_yticks(y)
    ax.set_yticklabels(ordered, fontsize=7)
    ax.set_xlabel("Non-null rate")
    ax.set_xlim(0, 1)
    ax.set_title(f"KDE Leaf Non-Null Rates by Source (n_leaves={n})")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_total_filled_fields(
    sources: list[tuple[str, dict[str, Any], str]],
    out: Path,
    total_possible_leaves: int,
) -> None:
    labels = [s[0] for s in sources]
    means = [s[1]["filled_per_incident"] for s in sources]
    ns = [s[1]["incidents"] for s in sources]
    colors = [s[2] for s in sources]

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(range(len(labels)), means, color=colors)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Mean populated leaf fields per incident")
    title = "Average Populated KDE Leaf Fields per Incident by Source"
    ax.set_title(title)

    ymax = max(means) if means else 1
    for bar, mean, n in zip(bars, means, ns):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + ymax * 0.01,
            f"{mean:.1f}\nn={n}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_ylim(0, ymax * 1.18 if ymax else 1)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


async def main_async(args: argparse.Namespace) -> None:
    gt, v1 = await fetch_api_sources(
        args.base_url, args.auth_token, Path(args.ids_file)
    )
    m54 = load_metrics_json(Path(args.metrics_54))
    m4o = load_metrics_json(Path(args.metrics_4o))

    sources = [
        ("Validated Set", gt, "#444"),
        ("IUU+DB", v1, "steelblue"),
        ("5.4-mini", m54, "#ff8c42"),
        ("4o-mini", m4o, "#6aaa64"),
    ]

    leaf_union: set[str] = set()
    for _, src, _ in sources:
        leaf_union.update(
            k
            for k in src["rates"].keys()
            if "." in k and not _is_excluded(k, KDE_FIELD_EXCLUDE)
        )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    plot_per_leaf_fill_rates(sources, out_dir / "kde_leaf_fill_rates_by_source.png")
    plot_total_filled_fields(
        sources,
        out_dir / "kde_leaf_filled_total_by_source.png",
        total_possible_leaves=len(leaf_union),
    )
    logger.info("Wrote figures to %s", out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument("--auth-token", default=os.environ.get("AUTH_TOKEN"))
    parser.add_argument("--ids-file", default="scripts/data/ids.csv")
    parser.add_argument("--metrics-4o", default="scripts/4o-metrics.json")
    parser.add_argument("--metrics-54", default="scripts/54-metrics.json")
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
