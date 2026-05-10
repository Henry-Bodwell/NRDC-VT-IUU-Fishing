"""Compare AI-extracted (v1) vs current human-reviewed state for a list of Sources.

Talks only to the public HTTP API:
    GET /api/sources/{id}                    -> current source
    GET /api/incidents/{id}                  -> current incident
    GET /api/logs/{id}/version/1             -> reconstructed v1 state

Outputs aggregate stats on:
  A. Source scope classification transitions
  B. IUU type transitions (added / removed / unchanged)
  C. IUU subtype transitions
  D. KDE field changes (top-level + leaf-level): untouched / missed / changed / removed

Usage:
    python scripts/review_analysis.py \
        --ids-file source_ids.json \
        --base-url http://localhost:8000 \
        --auth-token "$AUTH_TOKEN" \
        --output scripts/review_analysis.json

The auth token is the same NextAuth JWT used by webScraper/upload_scraped_data.py
(/api/logs requires admin auth). May also be supplied via AUTH_TOKEN env var.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import httpx

logger = logging.getLogger(__name__)


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def classify_change(orig: Any, curr: Any) -> str:
    o_empty = is_empty(orig)
    c_empty = is_empty(curr)
    if o_empty and c_empty:
        return "untouched"
    if o_empty and not c_empty:
        return "missed"
    if not o_empty and c_empty:
        return "removed"
    if orig == curr:
        return "untouched"
    return "changed"


def flatten(obj: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    """Yield (dotted_path, value) for every leaf in a nested dict.

    Lists are treated as leaves (compared whole) so things like
    speciesInvolved keep order/identity semantics.
    """
    if isinstance(obj, dict):
        if not obj:
            yield prefix, obj
            return
        for k, v in obj.items():
            child = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                yield from flatten(v, child)
            else:
                yield child, v
    else:
        yield prefix, obj


def load_ids(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x) for x in data]
        if isinstance(data, dict) and "ids" in data:
            return [str(x) for x in data["ids"]]
        raise ValueError("JSON file must be a list of IDs or {'ids': [...]}")
    if path.suffix.lower() == ".csv":
        reader = csv.reader(text.splitlines())
        rows = list(reader)
        if not rows:
            return []
        header = [c.strip().lower() for c in rows[0]]
        if "id" in header:
            idx = header.index("id")
            return [r[idx].strip() for r in rows[1:] if r and r[idx].strip()]
        return [r[0].strip() for r in rows if r and r[0].strip()]
    return [line.strip() for line in text.splitlines() if line.strip()]


def get_iuu_types(classification: dict | None) -> set[str]:
    if not classification:
        return set()
    items = classification.get("iuuClassifications") or []
    return {c.get("IUUType") for c in items if c.get("IUUType")}


def get_iuu_subtypes(classification: dict | None) -> set[str]:
    if not classification:
        return set()
    items = classification.get("iuuClassifications") or []
    out: set[str] = set()
    for c in items:
        for sub in c.get("IUUSubType") or []:
            if sub:
                out.add(sub)
    return out


def extract_link_id(link: Any) -> str | None:
    """Pull an ObjectId string out of a Beanie Link serialization.

    The shape can vary depending on whether links were fetched: it may be a
    plain string, {"id": "..."}, {"_id": "..."}, {"$id": "..."}, an oid-like
    {"$oid": "..."}, or a fully expanded incident document.
    """
    if link is None:
        return None
    if isinstance(link, str):
        return link
    if isinstance(link, dict):
        for key in ("id", "_id", "$id"):
            v = link.get(key)
            if isinstance(v, str):
                return v
            if isinstance(v, dict) and "$oid" in v:
                return v["$oid"]
        if "$oid" in link:
            return link["$oid"]
    return None


class ApiClient:
    def __init__(self, base_url: str, auth_token: str | None, timeout: float = 30.0):
        headers = {"Accept": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> dict | None:
        try:
            resp = await self._client.get(path)
        except httpx.HTTPError as exc:
            logger.warning("GET %s failed: %s", path, exc)
            return None
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning("GET %s -> %d: %s", path, resp.status_code, resp.text[:200])
            return None
        return resp.json()

    async def get_source(self, source_id: str) -> dict | None:
        return await self._get(f"/api/sources/{source_id}")

    async def get_incident(self, incident_id: str) -> dict | None:
        return await self._get(f"/api/incidents/{incident_id}")

    async def get_v1_state(self, document_id: str) -> dict | None:
        result = await self._get(f"/api/logs/{document_id}/version/1")
        if not result:
            return None
        return result.get("state")


def diff_source_scope(orig_state: dict | None, curr: dict | None, acc: dict) -> None:
    def scope_of(state: dict | None) -> str:
        if not state:
            return "<missing>"
        scope = state.get("article_scope") or {}
        return scope.get("articleType") or "<none>"

    acc["source_scope"][f"{scope_of(orig_state)} -> {scope_of(curr)}"] += 1


def diff_iuu_types(orig: dict, curr: dict, acc: dict) -> None:
    orig_set = get_iuu_types(orig.get("incident_classification"))
    curr_set = get_iuu_types(curr.get("incident_classification"))
    if orig_set == curr_set:
        acc["iuu_type_unchanged"] += 1
        return
    for added in curr_set - orig_set:
        acc["iuu_type_added"][added] += 1
    for removed in orig_set - curr_set:
        acc["iuu_type_removed"][removed] += 1


def diff_iuu_subtypes(orig: dict, curr: dict, acc: dict) -> None:
    orig_set = get_iuu_subtypes(orig.get("incident_classification"))
    curr_set = get_iuu_subtypes(curr.get("incident_classification"))
    if orig_set == curr_set:
        acc["iuu_subtype_unchanged"] += 1
        return
    for added in curr_set - orig_set:
        acc["iuu_subtype_added"][added] += 1
    for removed in orig_set - curr_set:
        acc["iuu_subtype_removed"][removed] += 1


def diff_kde_top_level(orig: dict, curr: dict, acc: dict) -> None:
    orig_ext = orig.get("extracted_information") or {}
    curr_ext = curr.get("extracted_information") or {}
    for key in set(orig_ext.keys()) | set(curr_ext.keys()):
        bucket = classify_change(orig_ext.get(key), curr_ext.get(key))
        acc["kde_top"][key][bucket] += 1


def diff_kde_leaf(orig: dict, curr: dict, acc: dict) -> None:
    orig_flat = dict(flatten(orig.get("extracted_information") or {}))
    curr_flat = dict(flatten(curr.get("extracted_information") or {}))
    for key in set(orig_flat.keys()) | set(curr_flat.keys()):
        bucket = classify_change(orig_flat.get(key), curr_flat.get(key))
        acc["kde_leaf"][key][bucket] += 1


def make_accumulators() -> dict:
    return {
        "source_scope": Counter(),
        "iuu_type_added": Counter(),
        "iuu_type_removed": Counter(),
        "iuu_type_unchanged": 0,
        "iuu_subtype_added": Counter(),
        "iuu_subtype_removed": Counter(),
        "iuu_subtype_unchanged": 0,
        "kde_top": defaultdict(lambda: Counter()),
        "kde_leaf": defaultdict(lambda: Counter()),
        "skipped": [],
        "counts": {
            "sources_processed": 0,
            "sources_missing": 0,
            "incidents_processed": 0,
            "incidents_skipped": 0,
        },
    }


async def run(
    ids_file: Path, output: Path, base_url: str, auth_token: str | None
) -> None:
    ids = load_ids(ids_file)
    logger.info("Loaded %d source IDs", len(ids))

    acc = make_accumulators()
    seen_incidents: set[str] = set()
    api = ApiClient(base_url, auth_token)
    try:
        for raw_id in ids:
            source = await api.get_source(raw_id)
            if not source:
                acc["counts"]["sources_missing"] += 1
                acc["skipped"].append({"id": raw_id, "reason": "source_not_found"})
                continue

            v1_state = await api.get_v1_state(raw_id)
            diff_source_scope(v1_state, source, acc)
            acc["counts"]["sources_processed"] += 1

            for link in source.get("incidents") or []:
                incident_id = extract_link_id(link)
                if not incident_id or incident_id in seen_incidents:
                    continue
                seen_incidents.add(incident_id)

                # If the source response already inlined the full incident, use it
                if isinstance(link, dict) and "extracted_information" in link:
                    curr = link
                else:
                    curr = await api.get_incident(incident_id)
                    if not curr:
                        acc["counts"]["incidents_skipped"] += 1
                        acc["skipped"].append(
                            {"id": incident_id, "reason": "incident_not_found"}
                        )
                        continue

                inc_v1 = await api.get_v1_state(incident_id)
                if not inc_v1:
                    acc["counts"]["incidents_skipped"] += 1
                    acc["skipped"].append({"id": incident_id, "reason": "no_v1_state"})
                    continue

                diff_iuu_types(inc_v1, curr, acc)
                diff_iuu_subtypes(inc_v1, curr, acc)
                diff_kde_top_level(inc_v1, curr, acc)
                diff_kde_leaf(inc_v1, curr, acc)
                acc["counts"]["incidents_processed"] += 1
    finally:
        await api.aclose()

    print_summary(acc)
    write_json(acc, output)
    logger.info("Wrote detailed JSON to %s", output)


def print_summary(acc: dict) -> None:
    c = acc["counts"]
    print("\n=== Run summary ===")
    print(
        f"Sources processed: {c['sources_processed']}  "
        f"missing: {c['sources_missing']}"
    )
    print(
        f"Incidents processed: {c['incidents_processed']}  "
        f"skipped: {c['incidents_skipped']}"
    )

    print("\n=== A. Source scope transitions ===")
    for transition, count in sorted(acc["source_scope"].items(), key=lambda x: -x[1]):
        print(f"  {count:>4}  {transition}")

    print("\n=== B. IUU type ===")
    print(f"  unchanged: {acc['iuu_type_unchanged']}")
    print("  added by reviewer:")
    for k, v in acc["iuu_type_added"].most_common():
        print(f"    {v:>4}  {k}")
    print("  removed by reviewer:")
    for k, v in acc["iuu_type_removed"].most_common():
        print(f"    {v:>4}  {k}")

    print("\n=== C. IUU subtype ===")
    print(f"  unchanged: {acc['iuu_subtype_unchanged']}")
    print("  added by reviewer:")
    for k, v in acc["iuu_subtype_added"].most_common():
        print(f"    {v:>4}  {k}")
    print("  removed by reviewer:")
    for k, v in acc["iuu_subtype_removed"].most_common():
        print(f"    {v:>4}  {k}")

    print("\n=== D1. KDE top-level (per-incident) ===")
    print(
        f"  {'field':<32} {'untouched':>10} {'missed':>8} "
        f"{'changed':>8} {'removed':>8}"
    )
    for field in sorted(acc["kde_top"].keys()):
        b = acc["kde_top"][field]
        print(
            f"  {field:<32} {b.get('untouched', 0):>10} "
            f"{b.get('missed', 0):>8} {b.get('changed', 0):>8} "
            f"{b.get('removed', 0):>8}"
        )

    print("\n=== D2. KDE leaf-level (top 30 by total non-untouched) ===")
    leaf_items = []
    for field, b in acc["kde_leaf"].items():
        touched = b.get("missed", 0) + b.get("changed", 0) + b.get("removed", 0)
        leaf_items.append((touched, field, b))
    leaf_items.sort(reverse=True)
    print(
        f"  {'field':<60} {'untouched':>10} {'missed':>8} "
        f"{'changed':>8} {'removed':>8}"
    )
    for _, field, b in leaf_items[:30]:
        print(
            f"  {field:<60} {b.get('untouched', 0):>10} "
            f"{b.get('missed', 0):>8} {b.get('changed', 0):>8} "
            f"{b.get('removed', 0):>8}"
        )
    print(f"  (full per-leaf breakdown of {len(leaf_items)} fields in JSON output)")


def write_json(acc: dict, path: Path) -> None:
    serializable = {
        "counts": acc["counts"],
        "source_scope": dict(acc["source_scope"]),
        "iuu_type": {
            "unchanged": acc["iuu_type_unchanged"],
            "added": dict(acc["iuu_type_added"]),
            "removed": dict(acc["iuu_type_removed"]),
        },
        "iuu_subtype": {
            "unchanged": acc["iuu_subtype_unchanged"],
            "added": dict(acc["iuu_subtype_added"]),
            "removed": dict(acc["iuu_subtype_removed"]),
        },
        "kde_top": {k: dict(v) for k, v in acc["kde_top"].items()},
        "kde_leaf": {k: dict(v) for k, v in acc["kde_leaf"].items()},
        "skipped": acc["skipped"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ids-file", required=True, type=Path, help="JSON/CSV file of Source IDs"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://localhost:8000"),
        help="API base URL (default: http://localhost:8000 or $API_BASE_URL)",
    )
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("AUTH_TOKEN"),
        help="Admin bearer token (or set AUTH_TOKEN env var). /api/logs requires it.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scripts/review_analysis.json"),
        help="Path for detailed JSON output",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.auth_token:
        logger.warning(
            "No auth token provided; /api/logs calls will likely 401. "
            "Pass --auth-token or set AUTH_TOKEN."
        )

    asyncio.run(run(args.ids_file, args.output, args.base_url, args.auth_token))


if __name__ == "__main__":
    main()
