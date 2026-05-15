"""Shared helpers for review_analysis, model_metrics, and baseline_extraction scripts.

Pure utility code: API client, diff helpers, accumulator builders, ID loading.
No CLI surface; import from a script's main module.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import httpx

logger = logging.getLogger(__name__)

EXCLUDED_LEAVES = {
    "eventData.eventCountry",
    "eventData.enforcementCountry",
}

EXCLUDED_LEAF_NAMES = {"verified", "description"}


def is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def classify_change(orig: Any, curr: Any) -> str:
    """Classify a (predicted, truth) slot judgment into one of five IE buckets.

    Bucket semantics — `orig` is the model prediction, `curr` is gold truth:
      - correct        : both populated, values equal           (TP)
      - correct_empty  : both empty                             (TN; excluded
                                                                 from rate
                                                                 denominators)
      - missing        : pred empty, truth populated            (FN)
      - spurious       : pred populated, truth empty            (FP)
      - mismatch       : both populated, values differ          (FP and FN
                                                                 under strict
                                                                 scoring)
    """
    o_empty = is_empty(orig)
    c_empty = is_empty(curr)
    if o_empty and c_empty:
        return "correct_empty"
    if o_empty and not c_empty:
        return "missing"
    if not o_empty and c_empty:
        return "spurious"
    if orig == curr:
        return "correct"
    return "mismatch"


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

    async def get_overview(self, overview_id: str) -> dict | None:
        return await self._get(f"/api/overviews/{overview_id}")

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

    acc["source_scope"][(scope_of(orig_state), scope_of(curr))] += 1


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


def strip_excluded(ext: dict) -> dict:
    """Return a copy of extracted_information with EXCLUDED_LEAVES removed."""
    if not ext:
        return {}
    out: dict = {}
    for top_key, top_val in ext.items():
        if top_key in EXCLUDED_LEAF_NAMES:
            continue
        if isinstance(top_val, dict):
            filtered = {
                k: v
                for k, v in top_val.items()
                if f"{top_key}.{k}" not in EXCLUDED_LEAVES
                and k not in EXCLUDED_LEAF_NAMES
            }
            out[top_key] = filtered
        else:
            out[top_key] = top_val
    return out


def diff_kde_top_level(orig: dict, curr: dict, acc: dict) -> None:
    orig_ext = strip_excluded(orig.get("extracted_information") or {})
    curr_ext = strip_excluded(curr.get("extracted_information") or {})
    for key in set(orig_ext.keys()) | set(curr_ext.keys()):
        bucket = classify_change(orig_ext.get(key), curr_ext.get(key))
        acc["kde_top"][key][bucket] += 1


def diff_kde_leaf(orig: dict, curr: dict, acc: dict) -> None:
    orig_flat = dict(flatten(orig.get("extracted_information") or {}))
    curr_flat = dict(flatten(curr.get("extracted_information") or {}))
    for key in set(orig_flat.keys()) | set(curr_flat.keys()):
        if key in EXCLUDED_LEAVES:
            continue
        if key.rsplit(".", 1)[-1] in EXCLUDED_LEAF_NAMES:
            continue
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
