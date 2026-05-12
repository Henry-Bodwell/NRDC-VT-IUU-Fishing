"""Export a per-incident leaf-field presence matrix as CSV for biclustering.

Talks to the public stats endpoint:
    GET /api/incidents/stats/leaf-presence

Output columns:
    incident_id, iuu_types, <leaf_path_1>, <leaf_path_2>, ...

``iuu_types`` is a semicolon-joined list of the incident's IUU classifications.
Leaf-path columns are 0/1; list-of-anything fields are treated as one leaf.

Usage:
    python scripts/export_leaf_presence_csv.py \
        --base-url http://localhost:8000 \
        --output scripts/data/leaf_presence.csv
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


def write_csv(payload: dict, out: Path) -> int:
    leaf_paths = payload.get("leaf_paths", [])
    incidents = payload.get("incidents", [])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["incident_id", "iuu_types", *leaf_paths])
        for inc in incidents:
            writer.writerow(
                [
                    inc.get("id", ""),
                    ";".join(inc.get("iuu_types") or []),
                    *inc.get("presence", []),
                ]
            )
    return len(incidents)


async def main_async(args: argparse.Namespace) -> None:
    logger.info("Fetching leaf-presence matrix from %s", args.base_url)
    payload = await fetch(args.base_url, args.auth_token)
    n = write_csv(payload, args.output)
    logger.info(
        "Wrote %d incidents x %d leaves to %s",
        n,
        len(payload.get("leaf_paths", [])),
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
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
