"""Export (enforcementCountry, quarter, count) aggregates as CSV.

Long-format table suitable for maximum-entropy modeling of enforcement
activity over space x time.

Talks to:
    GET /api/incidents/stats/enforcement-country-by-quarter

Quarter format: ``YYYY-Q[1-4]`` derived from ``eventData.eventDate``.
Rows missing either field (or with the ``NA`` sentinel) are excluded.

Usage:
    python scripts/export_enforcement_quarter_csv.py \
        --base-url http://localhost:8000 \
        --output scripts/data/enforcement_country_by_quarter.csv
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


async def fetch(base_url: str, auth_token: str | None) -> list[dict]:
    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"), headers=headers, timeout=60.0
    ) as client:
        r = await client.get("/api/incidents/stats/enforcement-country-by-quarter")
        r.raise_for_status()
        return r.json().get("counts", [])


def write_csv(rows: list[dict], out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["country_code", "quarter", "count"])
        for r in rows:
            writer.writerow([r.get("country_code"), r.get("quarter"), r.get("count")])
    return len(rows)


async def main_async(args: argparse.Namespace) -> None:
    logger.info("Fetching enforcement-country-by-quarter from %s", args.base_url)
    rows = await fetch(args.base_url, args.auth_token)
    n = write_csv(rows, args.output)
    total = sum(r.get("count", 0) for r in rows)
    logger.info(
        "Wrote %d (country, quarter) rows (sum=%d) to %s", n, total, args.output
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
        default=Path("scripts/data/enforcement_country_by_quarter.csv"),
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
