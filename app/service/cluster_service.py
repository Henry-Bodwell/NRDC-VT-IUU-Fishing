"""Cluster lifecycle: automatic rebuilds, manual curation, and summaries."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import numpy as np
from beanie import PydanticObjectId
from beanie.operators import In

from app.audit.context import AuditContext
from app.clustering.engine import (
    DEFAULT_MEMBERSHIP_THRESHOLD,
    DEFAULT_MIN_CLUSTER_SIZE,
    ExistingCluster,
    centroid_of,
    find_clusters,
    normalize_rows,
    reconcile,
)
from app.dedup.kde_compare import parse_date
from app.models.clusters import Cluster, MemberType, link_id, member_key
from app.models.incidents import IncidentReport, IndustryOverview
from app.rag.document_text import incident_iuu_types
from app.rag.vector_store import (
    DOC_TYPE_CLUSTER,
    DOC_TYPE_INCIDENT,
    DOC_TYPE_OVERVIEW,
    get_document_store,
)

logger = logging.getLogger(__name__)

SYSTEM_USER = "system:clustering"

# Members (most central first) shown to the LLM when summarising.
SUMMARY_MAX_MEMBERS = 15
SUMMARY_MAX_CHARS = 600

Summarizer = Callable[[list[str], str], Awaitable[dict]]


def _split_key(key: str) -> tuple[str, str]:
    doc_type, doc_id = key.split(":", 1)
    return doc_type, doc_id


async def _dspy_summarizer(member_descriptions: list[str], aggregates: str) -> dict:
    """Default summarizer: the ClusterSummary DSPy signature."""
    import dspy

    from app.dspy_files.config import setup_dspy
    from app.dspy_files.signatures import ClusterSummary

    lm = setup_dspy(api_key=os.getenv("OPENAI_API_KEY"), max_tokens=1500)
    with dspy.context(lm=lm):
        result = await dspy.Predict(ClusterSummary).acall(
            member_descriptions=member_descriptions, aggregates=aggregates
        )
    return {
        "title": result.title,
        "summary": result.summary,
        "keywords": list(result.keywords or []),
    }


class ClusterService:
    # ── Queries ────────────────────────────────────────────────────

    @staticmethod
    async def get(cluster_id: str) -> Cluster | None:
        return await Cluster.get(cluster_id, fetch_links=False)

    @staticmethod
    async def clusters_for(doc_type: MemberType, doc_id: str) -> list[Cluster]:
        """Active clusters containing a document (via the multikey index)."""
        field = "incidents.$id" if doc_type == DOC_TYPE_INCIDENT else "overviews.$id"
        return await Cluster.find(
            {field: PydanticObjectId(doc_id), "status": "active"},
            fetch_links=False,
        ).to_list()

    @staticmethod
    async def member_labels(cluster: Cluster) -> list[dict]:
        """Members with a short label, most central first."""
        incident_ids = [PydanticObjectId(link_id(i)) for i in cluster.incidents]
        overview_ids = [PydanticObjectId(link_id(o)) for o in cluster.overviews]
        out = []
        if incident_ids:
            for doc in await IncidentReport.find(
                In(IncidentReport.id, incident_ids)
            ).to_list():
                out.append(
                    {
                        "doc_type": DOC_TYPE_INCIDENT,
                        "doc_id": str(doc.id),
                        "label": doc.extracted_information.description,
                    }
                )
        if overview_ids:
            for doc in await IndustryOverview.find(
                In(IndustryOverview.id, overview_ids)
            ).to_list():
                out.append(
                    {
                        "doc_type": DOC_TYPE_OVERVIEW,
                        "doc_id": str(doc.id),
                        "label": doc.extracted_information.summary,
                    }
                )
        for item in out:
            item["score"] = cluster.member_scores.get(
                member_key(item["doc_type"], item["doc_id"])
            )
        out.sort(
            key=lambda m: m["score"] if m["score"] is not None else -1.0, reverse=True
        )
        return out

    # ── Centroids ──────────────────────────────────────────────────

    @staticmethod
    async def _refresh_centroid(cluster: Cluster) -> None:
        """Recompute the centroid and member scores from stored member vectors."""
        keys = [_split_key(k) for k in cluster.member_keys()]
        store = get_document_store()
        try:
            vectors = await store.get_document_vectors(keys)
            if not vectors:
                await store.delete_document(DOC_TYPE_CLUSTER, str(cluster.id))
                return
            order = list(vectors)
            matrix = normalize_rows(np.asarray([vectors[k] for k in order]))
            centroid = centroid_of(matrix)
            sims = matrix @ centroid
            cluster.member_scores = {
                member_key(*k): round(float(s), 4) for k, s in zip(order, sims)
            }
            await store.upsert_vectors(
                [(DOC_TYPE_CLUSTER, str(cluster.id), centroid.tolist(), {})]
            )
        except Exception as e:
            logger.warning(f"Could not refresh centroid for cluster {cluster.id}: {e}")

    # ── Manual curation ────────────────────────────────────────────

    @staticmethod
    async def create(
        title: str,
        summary: str | None = None,
        keywords: list[str] | None = None,
        members: list[tuple[str, str]] | None = None,
    ) -> Cluster:
        cluster = Cluster(
            title=title,
            summary=summary,
            keywords=keywords or [],
            origin="user",
            summary_stale=summary is None,
        )
        for doc_type, doc_id in members or []:
            cluster.add_member(doc_type, doc_id)
        await cluster.insert()
        if members:
            await ClusterService._refresh_centroid(cluster)
            await cluster.save()
        return cluster

    @staticmethod
    async def _assert_member_exists(doc_type: str, doc_id: str) -> None:
        model = IncidentReport if doc_type == DOC_TYPE_INCIDENT else IndustryOverview
        if await model.find_one(model.id == PydanticObjectId(doc_id)) is None:
            raise ValueError(f"{doc_type} {doc_id} not found")

    @staticmethod
    async def add_member(
        cluster: Cluster, doc_type: MemberType, doc_id: str
    ) -> Cluster:
        await ClusterService._assert_member_exists(doc_type, doc_id)
        cluster.add_member(doc_type, doc_id)
        await ClusterService._refresh_centroid(cluster)
        await cluster.save()
        return cluster

    @staticmethod
    async def remove_member(
        cluster: Cluster, doc_type: MemberType, doc_id: str
    ) -> Cluster:
        cluster.remove_member(doc_type, doc_id, exclude=True)
        await ClusterService._refresh_centroid(cluster)
        await cluster.save()
        return cluster

    @staticmethod
    async def suggestions(cluster: Cluster, k: int = 10) -> list[dict]:
        """Documents near the centroid that are not (and were not removed as) members."""
        store = get_document_store()
        centroid = await store.get_document_vector(DOC_TYPE_CLUSTER, str(cluster.id))
        if centroid is None:
            return []
        skip = cluster.member_keys() | set(cluster.excluded_ids)
        hits = await store.similar_to_vector(
            centroid,
            k=k + len(skip),
            doc_types=[DOC_TYPE_INCIDENT, DOC_TYPE_OVERVIEW],
        )
        return [
            {"doc_type": h.doc_type, "doc_id": h.doc_id, "score": round(h.score, 4)}
            for h in hits
            if member_key(h.doc_type, h.doc_id) not in skip
        ][:k]

    @staticmethod
    async def delete(cluster: Cluster) -> None:
        await cluster.delete()
        try:
            await get_document_store().delete_document(
                DOC_TYPE_CLUSTER, str(cluster.id)
            )
        except Exception as e:
            logger.warning(f"Could not delete centroid for cluster {cluster.id}: {e}")

    @staticmethod
    async def remove_document_everywhere(doc_type: str, doc_id) -> None:
        """Drop a deleted document from every cluster (best-effort, unaudited)."""
        field = "incidents" if doc_type == DOC_TYPE_INCIDENT else "overviews"
        try:
            await Cluster.get_pymongo_collection().update_many(
                {f"{field}.$id": PydanticObjectId(str(doc_id))},
                {
                    "$pull": {field: {"$id": PydanticObjectId(str(doc_id))}},
                    "$unset": {
                        f"member_scores.{member_key(doc_type, str(doc_id))}": ""
                    },
                    "$set": {"summary_stale": True},
                },
            )
        except Exception as e:
            logger.warning(f"Could not remove {doc_type} {doc_id} from clusters: {e}")

    # ── Summaries ──────────────────────────────────────────────────

    @staticmethod
    async def _summary_inputs(cluster: Cluster) -> tuple[list[str], str]:
        ranked = sorted(
            cluster.member_keys(),
            key=lambda k: cluster.member_scores.get(k, 0.0),
            reverse=True,
        )
        incident_ids = [
            PydanticObjectId(_split_key(k)[1])
            for k in ranked
            if k.startswith("incident:")
        ]
        overview_ids = [
            PydanticObjectId(_split_key(k)[1])
            for k in ranked
            if k.startswith("overview:")
        ]
        incidents = {
            str(d.id): d
            for d in await IncidentReport.find(
                In(IncidentReport.id, incident_ids)
            ).to_list()
        }
        overviews = {
            str(d.id): d
            for d in await IndustryOverview.find(
                In(IndustryOverview.id, overview_ids)
            ).to_list()
        }

        species: Counter[str] = Counter()
        countries: Counter[str] = Counter()
        flags: Counter[str] = Counter()
        iuu: Counter[str] = Counter()
        dates = []
        descriptions = []

        for key in ranked:
            doc_type, doc_id = _split_key(key)
            if doc_type == DOC_TYPE_INCIDENT and doc_id in incidents:
                inc = incidents[doc_id]
                data = inc.extracted_information
                for sp in data.speciesInvolved or []:
                    name = sp.speciesCommonName or sp.scientificName
                    if name:
                        species[name.strip().lower()] += 1
                if data.eventData and data.eventData.eventCountry:
                    countries[data.eventData.eventCountry.strip()] += 1
                if data.vesselInformation and data.vesselInformation.vesselFlag:
                    flags[data.vesselInformation.vesselFlag.strip()] += 1
                for t in incident_iuu_types(inc):
                    iuu[t] += 1
                parsed = parse_date(
                    data.eventData.eventDate if data.eventData else None
                )
                if parsed:
                    dates.append(parsed.start)
                text = data.description
                prefix = "[Incident]"
            elif doc_type == DOC_TYPE_OVERVIEW and doc_id in overviews:
                ov = overviews[doc_id].extracted_information
                for sp in ov.species or []:
                    name = sp.speciesCommonName or sp.scientificName
                    if name:
                        species[name.strip().lower()] += 1
                for c in ov.countries or []:
                    countries[c.strip()] += 1
                text = ov.summary
                prefix = "[Overview]"
            else:
                continue
            if len(descriptions) < SUMMARY_MAX_MEMBERS and text:
                descriptions.append(f"{prefix} {text[:SUMMARY_MAX_CHARS]}")

        def top(counter: Counter[str]) -> str:
            return ", ".join(f"{k} ({v})" for k, v in counter.most_common(8)) or "none"

        date_range = (
            f"{min(dates).isoformat()} to {max(dates).isoformat()}"
            if dates
            else "unknown"
        )
        aggregates = "\n".join(
            [
                f"Members: {len(incidents)} incidents, {len(overviews)} overviews",
                f"Species: {top(species)}",
                f"Countries: {top(countries)}",
                f"Flag states: {top(flags)}",
                f"IUU types: {top(iuu)}",
                f"Event dates: {date_range}",
            ]
        )
        return descriptions, aggregates

    @staticmethod
    async def summarize(
        cluster: Cluster, summarizer: Optional[Summarizer] = None
    ) -> Cluster:
        """Generate title/summary/keywords. A user-written title is kept."""
        descriptions, aggregates = await ClusterService._summary_inputs(cluster)
        if not descriptions:
            return cluster
        result = await (summarizer or _dspy_summarizer)(descriptions, aggregates)
        if cluster.origin == "auto" or cluster.title in ("", "Untitled cluster"):
            cluster.title = result["title"].strip()
        cluster.summary = result["summary"].strip()
        cluster.keywords = [k.strip() for k in result["keywords"] if k.strip()]
        cluster.summary_stale = False
        cluster.summary_generated_at = datetime.now(timezone.utc)
        await cluster.save()
        return cluster

    # ── Automatic rebuild ──────────────────────────────────────────

    @staticmethod
    async def rebuild(
        *,
        min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
        membership_threshold: float = DEFAULT_MEMBERSHIP_THRESHOLD,
        summarize: bool = True,
        summarizer: Optional[Summarizer] = None,
        user_id: str = SYSTEM_USER,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ) -> dict[str, Any]:
        """Re-cluster every indexed incident/overview and reconcile with storage.

        Automatic clusters are matched to proposals by member overlap and
        updated in place (keeping ids and user exclusions), new proposals become
        new clusters, and automatic clusters with no match are archived. User
        clusters are never modified.
        """
        store = get_document_store()
        vectors = await store.scroll_vectors([DOC_TYPE_INCIDENT, DOC_TYPE_OVERVIEW])
        keys = [member_key(v.doc_type, v.doc_id) for v in vectors]
        if progress_callback:
            await progress_callback("clustering", 10)

        # HDBSCAN is CPU-bound; keep the event loop responsive.
        proposals = await asyncio.to_thread(
            find_clusters,
            keys,
            [v.vector for v in vectors],
            min_cluster_size=min_cluster_size,
            membership_threshold=membership_threshold,
        )

        existing_docs = await Cluster.find(
            Cluster.origin == "auto", Cluster.status == "active", fetch_links=False
        ).to_list()
        existing_by_id = {str(c.id): c for c in existing_docs}
        plan = reconcile(
            proposals,
            [
                ExistingCluster(
                    id=str(c.id), members=c.member_keys(), excluded=set(c.excluded_ids)
                )
                for c in existing_docs
            ],
        )
        stats: dict[str, Any] = {
            "documents": len(vectors),
            "clusters_found": len(proposals),
            "updated": len(plan.updates),
            "created": len(plan.creates),
            "archived": len(plan.archives),
            "summarized": 0,
        }
        if dry_run:
            stats["proposals"] = [
                {"core_size": p.core_size, "members": sorted(p.members)}
                for p in proposals
            ]
            return stats
        if progress_callback:
            await progress_callback("saving", 50)

        touched: list[tuple[Cluster, list[float]]] = []
        with AuditContext.with_user(user_id):
            for cluster_id, proposal in plan.updates:
                cluster = existing_by_id[cluster_id]
                changed = cluster.set_members(proposal.scores)
                await cluster.save()
                touched.append((cluster, proposal.centroid))
                logger.info(
                    f"Cluster {cluster_id} updated (membership changed: {changed})"
                )
            for proposal in plan.creates:
                cluster = Cluster(origin="auto")
                cluster.set_members(proposal.scores)
                await cluster.insert()
                touched.append((cluster, proposal.centroid))
            for cluster_id in plan.archives:
                cluster = existing_by_id[cluster_id]
                cluster.status = "archived"
                await cluster.save()

        try:
            await store.upsert_vectors(
                [(DOC_TYPE_CLUSTER, str(c.id), centroid, {}) for c, centroid in touched]
            )
            for cluster_id in plan.archives:
                await store.delete_document(DOC_TYPE_CLUSTER, cluster_id)
        except Exception as e:
            logger.warning(f"Could not store cluster centroids: {e}")

        if summarize:
            stale = [c for c, _ in touched if c.summary_stale]
            with AuditContext.with_user(user_id):
                for i, cluster in enumerate(stale):
                    try:
                        await ClusterService.summarize(cluster, summarizer)
                        stats["summarized"] += 1
                    except Exception as e:
                        logger.warning(f"Summary failed for cluster {cluster.id}: {e}")
                    if progress_callback and stale:
                        await progress_callback(
                            "summarizing", 50 + int(50 * (i + 1) / len(stale))
                        )
        return stats
