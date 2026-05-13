"""Export a per-incident leaf-field presence matrix as CSV for biclustering.

Talks to the public stats endpoint:
    GET /api/incidents/stats/leaf-presence

Output columns:
    incident_id, iuu_types, <leaf_path_1>, <leaf_path_2>, ...

``iuu_types`` is a semicolon-joined list of the incident's IUU classifications.
Leaf-path columns are 0/1; list-of-anything fields are treated as one leaf.

Field-level exclusions are applied client-side. A leaf path is dropped when
it equals an excluded name or starts with ``<excluded>.`` (so excluding a
top-level field also drops every nested leaf under it).

Usage:
    python scripts/export_leaf_presence_csv.py \
        --base-url http://localhost:8000 \
        --output scripts/data/leaf_presence.csv \
        --exclude description --exclude chainOfCustody
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


DEFAULT_LEAF_EXCLUDE = {"description", "sanitaryLicenseID", "chainOfCustody"}


def _is_excluded(path: str, exclude: set[str]) -> bool:
    if path in exclude:
        return True
    return any(path.startswith(f"{e}.") for e in exclude)


async def fetch(base_url: str, auth_token: str | None) -> dict:
    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"), headers=headers, timeout=120.0
    ) as client:
        r = await client.get("/api/incidents/stats/leaf-presence")
        r.raise_for_status()
        return r.json()


def write_csv(payload: dict, out: Path, exclude: set[str]) -> tuple[int, int, int]:
    leaf_paths: list[str] = payload.get("leaf_paths", [])
    incidents = payload.get("incidents", [])

    keep_mask = [not _is_excluded(p, exclude) for p in leaf_paths]
    kept_paths = [p for p, keep in zip(leaf_paths, keep_mask) if keep]
    dropped = len(leaf_paths) - len(kept_paths)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["incident_id", "iuu_types", *kept_paths])
        for inc in incidents:
            presence = inc.get("presence", [])
            filtered = [v for v, keep in zip(presence, keep_mask) if keep]
            writer.writerow(
                [
                    inc.get("id", ""),
                    ";".join(inc.get("iuu_types") or []),
                    *filtered,
                ]
            )
    return len(incidents), len(kept_paths), dropped


async def main_async(args: argparse.Namespace) -> None:
    exclude = (
        set(args.exclude) if args.exclude is not None else set(DEFAULT_LEAF_EXCLUDE)
    )
    if exclude:
        logger.info("Excluding %d field(s): %s", len(exclude), sorted(exclude))

    logger.info("Fetching leaf-presence matrix from %s", args.base_url)
    payload = await fetch(args.base_url, args.auth_token)
    n_inc, n_leaves, dropped = write_csv(payload, args.output, exclude)
    logger.info(
        "Wrote %d incidents x %d leaves (%d excluded) to %s",
        n_inc,
        n_leaves,
        dropped,
        args.output,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument("--auth-token", default=os.environ.get("AUTH_TOKEN"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scripts/data/leaf_presence.csv"),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        help=(
            "Leaf path or top-level field to exclude. Repeat for multiple. "
            "Prefix-matches nested paths (e.g. 'vessel' drops 'vessel.name'). "
            "If omitted, defaults to: "
            f"{', '.join(sorted(DEFAULT_LEAF_EXCLUDE))}. "
            "Pass --no-default-excludes to start from an empty set."
        ),
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Disable the default exclude set; only --exclude values are used.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    if args.exclude is None and args.no_default_excludes:
        args.exclude = []
    elif args.exclude is not None and not args.no_default_excludes:
        args.exclude = list(set(args.exclude) | DEFAULT_LEAF_EXCLUDE)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
