import os
from typing import List, get_args, get_origin
from fastapi import HTTPException, status
from app.literals import IUUType
from app.models.incidents import IncidentReport
from app.models.incident_data import ExtractedIncidentData
from app.models.sources import Source, ArticleScopeClassification
from app.models.task import TaskStatus
from pymongo.errors import DuplicateKeyError
from app.dspy_files.news_analysis import (
    AnalysisOrchestrator,
    PipelineOutput,
    PipelineResult,
)
import logging
from app.dspy_files.content_extraction import ContentExtractor
from app.service.service import Service
from app.audit.context import AuditContext

logger = logging.getLogger(__name__)


class IncidentService(Service):
    """
    Service layer for incident reports. Allows for greater logging
    """

    @staticmethod
    async def _create_report(output: PipelineOutput) -> PipelineResult:
        if output.status == PipelineResult.DUPLICATE_HASHED_TEXT:
            logger.info(f"Text already exists in db: {output.source.id}")
            return output

        source = output.source

        if not source:
            logger.error("Analysis failed to produce a source")
            logger.error(f"Pipeline status {output.status}: {output.error_message}")

            return output

        if output.status != PipelineResult.UNRELATED_CONTENT:
            incidents = output.incidents
            industry = output.industry_overview

            if not output.has_incident and not output.has_overview:
                logger.error(
                    f"Analysis failed to produce a report for source: {source.id}"
                )
                logger.error(f"Pipeline status {output.status}: {output.error_message}")
                return output

            if not output.is_success:
                logger.error(
                    f"Analysis failed for source {source.id} with status {output.status}"
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Analysis failed with status: {output.status}: {output.error_message or 'No error message provided'}",
                )

            if output.has_incident:
                saved_incidents = []
                for incident in incidents:
                    try:
                        await incident.insert()
                        logger.info(
                            f"Successfully saved incident report: {incident.id}"
                        )
                        saved_incidents.append(incident)
                    except Exception as e:
                        logger.error(
                            f"Database save failed for report {incident.id}: {e}"
                        )
                        raise e
                source.incidents = saved_incidents
                output.incidents = saved_incidents
            if output.has_overview and industry:
                try:
                    await industry.insert()
                    logger.info(f"Successfully saved industry report: {industry.id}")
                    source.overview = industry
                except Exception as e:
                    logger.error(
                        f"Database save failed for industry report {industry.id}: {e}"
                    )
                    raise e

        try:
            await source.insert()
            logger.info(f"Successfully saved source: {source.id}")
        except DuplicateKeyError as e:
            logger.warning(
                f"Source with same content already exists (hash: {source.article_hash}). Fetching existing source."
            )
            existing_source = await Source.find_one(
                Source.article_hash == source.article_hash
            )
            if existing_source:
                if existing_source.id == source.id:
                    # Reclassification: source is already in DB, replace with updated state
                    logger.info(f"Replacing existing source in place: {source.id}")
                    await source.replace()
                    # Fall through to linking code below
                else:
                    # True concurrent duplicate race: different in-memory source, same content
                    output.source = existing_source
                    output.status = PipelineResult.DUPLICATE_HASHED_TEXT
                    logger.info(f"Using existing source: {existing_source.id}")
                    if output.has_incident:
                        for incident in output.incidents:
                            logger.warning(
                                f"Deleting orphaned incident {incident.id} from duplicate source race"
                            )
                            await incident.delete()
                    if output.has_overview and industry and hasattr(industry, "source"):
                        industry.source = existing_source
                        await industry.save()
                    return output
            else:
                logger.error(
                    f"DuplicateKeyError but couldn't find existing source: {e}"
                )
                raise e
        except Exception as e:
            logger.error(f"Database save failed for {source.id}: {e}")
            if output.has_incident:
                for incident in output.incidents:
                    logger.warning(
                        f"Source insert failed; deleting orphaned incident {incident.id}"
                    )
                    await incident.delete()
            if output.has_overview and industry and hasattr(industry, "source"):
                logger.warning(
                    f"Source insert failed; deleting orphaned industry overview {industry.id}"
                )
                await industry.delete()
            raise e

        if output.status == PipelineResult.UNRELATED_CONTENT:
            logger.info(f"Source {source.id} unrelated to IUU fishing")
            return output

        if output.has_incident:
            for incident in output.incidents:
                if incident.primary_source is None:
                    await incident.add_source(source, is_primary=True)
                else:
                    await incident.add_source(source, is_primary=False)

        if output.has_overview and industry and hasattr(industry, "source"):
            industry.source = source
            await industry.save()

        return output

    @staticmethod
    def _get_orchestrator() -> AnalysisOrchestrator:
        api = os.getenv("OPENAI_API_KEY")
        return AnalysisOrchestrator(api_key=api)

    @staticmethod
    async def create_report_from_url(url: str) -> PipelineOutput:

        logger.info(f"Starting analysis for URL: {url}")

        orchestrator = IncidentService._get_orchestrator()

        output = await orchestrator.run_full_analysis_from_url(url=url)

        results = await IncidentService._create_report(output)
        return results

    @staticmethod
    async def create_report_from_pdf(
        pdf_bytes: bytes, filename: str = "", context_data: dict = {}
    ) -> PipelineResult:

        logger.info(f"Starting analysis for file: {filename}")
        source = ContentExtractor.from_pdf(pdf_bytes)
        orchestrator = IncidentService._get_orchestrator()
        output = await orchestrator.analysis_from_source(source=source)

        results = await IncidentService._create_report(output=output)

        return results

    @staticmethod
    async def create_report_from_text(
        text: str,
        url: str = "",
        author: str = "",
        title: str = "",
        publisher: str = "",
        date=None,
        status: str = "user_input",
    ) -> PipelineResult:
        logger.info(f"Starting analysis for text: {text[:50]}")
        orchestrator = IncidentService._get_orchestrator()
        output = await orchestrator.run_full_analysis_from_text(
            text=text,
            url=url,
            author=author,
            title=title,
            publisher=publisher,
            publication_date=date,
            status=status,
        )

        results = await IncidentService._create_report(output)
        return results

    @staticmethod
    async def add_source_to_report(
        report_id: str, source_id: str, is_primary: bool = False
    ) -> IncidentReport:
        report = await IncidentReport.get(report_id, fetch_links=True)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID {report_id} not found",
            )

        source = await Source.get(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source with ID {source_id} not found",
            )

        await report.add_source(source, is_primary=is_primary)
        logger.info(f"Added source {source_id} to report {report_id}")
        # Re-fetch without links to avoid circular reference recursion during serialization
        return await IncidentReport.get(report_id, fetch_links=False)

    @staticmethod
    async def remove_source_from_report(
        report_id: str, source_id: str
    ) -> IncidentReport:
        report = await IncidentReport.get(report_id, fetch_links=True)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID {report_id} not found",
            )

        source = await Source.get(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source with ID {source_id} not found",
            )

        await report.remove_source(source)
        logger.info(f"Removed source {source_id} from report {report_id}")
        # Re-fetch without links to avoid circular reference recursion during serialization
        return await IncidentReport.get(report_id, fetch_links=False)

    @staticmethod
    async def update_report(report_id: str, update_data: dict) -> IncidentReport:
        return await Service.update_model(
            model_cls=IncidentReport,
            model_id=report_id,
            update_data=update_data,
            model_name="report",
        )

    @staticmethod
    async def delete_report(report_id: str) -> bool:
        return await Service.delete(
            model_cls=IncidentReport,
            model_id=report_id,
            model_name="report",
        )

    # ── Composable entry points ─────────────────────────────────────

    @staticmethod
    async def analyze_existing_source(
        source: Source,
        assumed_scope: str | None = None,
    ) -> PipelineOutput:
        """
        Run analysis on a pre-existing Source, optionally overriding its
        classification. Does NOT persist results -- call save_pipeline_output()
        on the returned PipelineOutput to save.

        Args:
            source: An existing Source object (may or may not be in the DB)
            assumed_scope: If provided, override source.article_scope.
                          One of: "Single Incident", "Multiple Incidents",
                          "Industry Overview", "Unrelated to IUU Fishing"

        Returns:
            PipelineOutput ready for persistence via save_pipeline_output()
        """
        if assumed_scope:
            source.article_scope = ArticleScopeClassification(
                articleType=assumed_scope,
                confidence=1.0,
            )

        orchestrator = IncidentService._get_orchestrator()
        return await orchestrator.analysis_from_source(source=source)

    @staticmethod
    async def save_pipeline_output(output: PipelineOutput) -> PipelineOutput:
        """
        Persist a PipelineOutput to the database.

        Handles inserting incidents, overview, and source; duplicate-race
        cleanup; and relationship linking.
        """
        return await IncidentService._create_report(output)

    @staticmethod
    async def run_analysis_with_task_tracking(
        task_id: str,
        input_type: str,
        **kwargs,
    ):
        """
        Wrapper that runs the analysis pipeline with task progress tracking.

        Args:
            task_id: The task ID to update with progress
            input_type: "url", "pdf", or "text"
            **kwargs: Arguments to pass to the appropriate create_report method
        """
        task = await TaskStatus.find_one(TaskStatus.task_id == task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        # Define progress callback that updates the task
        async def progress_callback(stage: str, percent: int):
            await task.update_progress(stage, percent)
            logger.info(f"Task {task_id}: {stage} - {percent}%")

        try:
            logger.info(f"Task {task_id}: Starting analysis")

            # Get orchestrator
            orchestrator = IncidentService._get_orchestrator()

            # Run analysis with progress callback (handles 0-80% progress)
            if input_type == "url":
                output = await orchestrator.run_full_analysis_from_url(
                    url=kwargs["url"], progress_callback=progress_callback
                )
            elif input_type == "pdf":
                source = ContentExtractor.from_pdf(kwargs["pdf_bytes"])

                # Apply metadata to the source if provided
                if "title" in kwargs and kwargs["title"]:
                    source.article_title = kwargs["title"]
                if "author" in kwargs and kwargs["author"]:
                    source.author = kwargs["author"]
                if "publisher" in kwargs and kwargs["publisher"]:
                    source.publisher = kwargs["publisher"]
                if "publication_date" in kwargs and kwargs["publication_date"]:
                    source.publication_date = kwargs["publication_date"]
                if "url" in kwargs and kwargs["url"]:
                    source.url = kwargs["url"]
                if "status" in kwargs and kwargs["status"]:
                    source.status = kwargs["status"]
                if "input_name" in kwargs and kwargs["input_name"]:
                    source.input_name = kwargs["input_name"]

                output = await orchestrator.analysis_from_source(
                    source=source, progress_callback=progress_callback
                )
            elif input_type == "text":
                output = await orchestrator.run_full_analysis_from_text(
                    text=kwargs["text"],
                    url=kwargs.get("url", None),
                    author=kwargs.get("author", None),
                    title=kwargs.get("title", None),
                    publisher=kwargs.get("publisher", None),
                    publication_date=kwargs.get("date", None),
                    status=kwargs.get("status", "user_input"),
                    input_name=kwargs.get("input_name", None),
                    progress_callback=progress_callback,
                )
            else:
                raise ValueError(f"Invalid input_type: {input_type}")

            # Set source_type if provided
            if "source_type" in kwargs and output.source:
                output.source.source_type = kwargs["source_type"]

            # Stage: Saving to database (80-90%)
            await progress_callback("saving", 85)
            logger.info(f"Task {task_id}: Saving to database")

            # Get user_id from task and set audit context
            user_id = task.user_id if task.user_id else "anonymous"
            with AuditContext.with_user(user_id):
                results = await IncidentService._create_report(output)

            await progress_callback("saving", 95)

            # Stage 6: Check if pipeline succeeded
            result_data = {
                "status": results.status,
                "source_id": str(results.source.id) if results.source else None,
                "incident_ids": (
                    [str(i.id) for i in results.incidents] if results.incidents else []
                ),
                "industry_overview_id": (
                    str(results.industry_overview.id)
                    if results.industry_overview
                    else None
                ),
                "article_scope": (
                    results.source.article_scope if results.source else None
                ),
                "error_message": results.error_message,
            }

            # Check if the pipeline actually succeeded
            if (
                results.is_success
                or results.is_unrelated
                or results.status == PipelineResult.DUPLICATE_HASHED_TEXT
            ):
                await task.mark_completed(result_data)
                logger.info(
                    f"Task {task_id}: Completed successfully with status {results.status}"
                )
            else:
                # Pipeline failed - mark task as failed
                error_msg = (
                    results.error_message
                    or f"Pipeline failed with status: {results.status}"
                )
                await task.mark_failed(error_msg)
                logger.error(
                    f"Task {task_id}: Failed with status {results.status}: {error_msg}"
                )

        except Exception as e:
            logger.error(f"Task {task_id} failed with error: {str(e)}")
            await task.mark_failed(str(e))
            raise

    def get_IUU_types(types: List[IUUType] | None = None) -> dict:

        all_types = {
            "Illegal Fishing": [
                "Exceeding catch quotas",
                "Keeping undersized fish",
                "Catching unauthorized or prohibited species",
                "Prohibited fishing gear",
                "Fishing in closed areas or closed seasons",
                "Invalid or no permit or license",
                "Obscuring vessel identity",
                "Unauthorized transshipment",
                "Falisfying Documents",
                "Obstructing inspectors",
                "Illegal bycatch practices",
            ],
            "Unreported Catch": [
                "Un/underreported target catch weight or size",
                "Un/underreported discards/bycatch weight or size",
                "Misreported target catch species",
                "Misreported non-target catch species",
                "Misreported location or timing of fishing",
                "Misreported gear",
                "Unreported transshipment activities",
            ],
            "Unregulated Fishing": [
                "Stateless vessel",
                "Fishing under flag not party to RFMO",
                "Fishing in unregulated areas or for unregulated stock",
            ],
            "Seafood Fraud or Mislabeling": [
                "Species mislabeling or fraud",
                "Production information fraud",
            ],
            "Forced Labor or Labor Abuse": [
                "Wage/Pay violations",
                "Abusive living conditions",
                "Abusive working conditions",
                "Inadequate crew size",
                "Physical or sexual violence",
                "Intimidation",
                "Families threatened",
                "Deception",
                "No work contracts",
                "Isolation",
                "Migrants threatened",
            ],
            "Circumventing Prohibitions or Sanctions": [
                "Circumventing sanctions (individuals or corporations)",
                "Circumventing import prohibitions (countries or products)",
            ],
            "Illegal Aquacultural Practices": [
                "Unapproved/non-native species",
                "Illegal sourcing of seed/broodstock",
                "Misrepresentation or falsification of farming operations",
                "Unlicensed/Unauthorized farm operations",
                "Stolen products",
            ],
            "Other": [
                "Information not sufficient to determine specific IUU+ behavior",
                "Crimes related to fishing or associated trade but distinct from IUU+ typology (e.g., murder of journalists investigating IUU+ fishing)",
                "Other",
            ],
        }
        if not types:
            return all_types

        return {type_name: all_types.get(type_name, []) for type_name in types}

    @staticmethod
    async def _country_code_counts(field_path: str) -> list[dict]:
        """Group incidents by a country-code field, excluding null and 'NA'."""
        pipeline = [
            {"$match": {field_path: {"$nin": [None, "NA"]}}},
            {"$group": {"_id": f"${field_path}", "count": {"$sum": 1}}},
            {"$sort": {"count": -1, "_id": 1}},
            {"$project": {"_id": 0, "country_code": "$_id", "count": 1}},
        ]
        return await IncidentReport.aggregate(pipeline).to_list()

    @staticmethod
    async def kde_distribution(iuu_type: IUUType | None = None) -> dict:
        """Return per-field non-null counts and rates over IncidentReport.extracted_information.

        Optionally filter by an IUU type (matches incident_classification.iuuClassifications.IUUType).
        """

        def _is_list_field(annotation) -> bool:
            if get_origin(annotation) is list:
                return True
            for arg in get_args(annotation):
                if get_origin(arg) is list:
                    return True
            return False

        list_fields = {
            name
            for name, info in ExtractedIncidentData.model_fields.items()
            if _is_list_field(info.annotation)
        }
        fields = list(ExtractedIncidentData.model_fields.keys())

        def _present_expr(field: str) -> dict:
            path = f"$extracted_information.{field}"
            if field in list_fields:
                return {
                    "$cond": [
                        {"$gt": [{"$size": {"$ifNull": [path, []]}}, 0]},
                        1,
                        0,
                    ]
                }
            return {"$cond": [{"$gt": [path, None]}, 1, 0]}

        pipeline: list[dict] = []
        if iuu_type and iuu_type != "all":
            pipeline.append(
                {
                    "$match": {
                        "incident_classification.iuuClassifications": {
                            "$elemMatch": {"IUUType": iuu_type}
                        }
                    }
                }
            )

        pipeline.append(
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    **{
                        f"{field}_count": {"$sum": _present_expr(field)}
                        for field in fields
                    },
                }
            }
        )

        results = await IncidentReport.aggregate(pipeline).to_list()
        if not results:
            return {"total": 0, "fields": {}}

        row = results[0]
        total = row["total"]
        if total == 0:
            return {"total": 0, "fields": {}}
        return {
            "total": total,
            "fields": {
                field: {
                    "count": row[f"{field}_count"],
                    "non_null_rate": round(row[f"{field}_count"] / total, 4),
                }
                for field in fields
            },
        }

    @staticmethod
    async def event_country_counts() -> list[dict]:
        return await IncidentService._country_code_counts(
            "extracted_information.eventData.eventCountry"
        )

    @staticmethod
    async def enforcement_country_counts() -> list[dict]:
        return await IncidentService._country_code_counts(
            "extracted_information.eventData.enforcementCountry"
        )

    @staticmethod
    async def year_counts() -> list[dict]:
        """Counts of incidents grouped by year extracted from eventDate (YYYY-MM-DD)."""
        pipeline = [
            {
                "$match": {
                    "extracted_information.eventData.eventDate": {
                        "$nin": [None, "", "NA"]
                    }
                }
            },
            {
                "$group": {
                    "_id": {
                        "$substr": [
                            "$extracted_information.eventData.eventDate",
                            0,
                            4,
                        ]
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"_id": {"$regex": r"^\d{4}$"}}},
            {"$sort": {"_id": 1}},
            {"$project": {"_id": 0, "year": "$_id", "count": 1}},
        ]
        return await IncidentReport.aggregate(pipeline).to_list()

    @staticmethod
    async def iuu_type_counts() -> list[dict]:
        """Counts of incidents per IUUType (an incident with N types contributes N rows)."""
        pipeline = [
            {"$unwind": "$incident_classification.iuuClassifications"},
            {
                "$group": {
                    "_id": "$incident_classification.iuuClassifications.IUUType",
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1, "_id": 1}},
            {"$project": {"_id": 0, "iuu_type": "$_id", "count": 1}},
        ]
        return await IncidentReport.aggregate(pipeline).to_list()

    @staticmethod
    async def iuu_subtype_counts() -> list[dict]:
        """Counts per (IUUType, IUUSubType) pair across all incidents."""
        pipeline = [
            {"$unwind": "$incident_classification.iuuClassifications"},
            {"$unwind": "$incident_classification.iuuClassifications.IUUSubType"},
            {
                "$group": {
                    "_id": {
                        "iuu_type": "$incident_classification.iuuClassifications.IUUType",
                        "subtype": "$incident_classification.iuuClassifications.IUUSubType",
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id.iuu_type": 1, "count": -1}},
            {
                "$project": {
                    "_id": 0,
                    "iuu_type": "$_id.iuu_type",
                    "subtype": "$_id.subtype",
                    "count": "$count",
                }
            },
        ]
        return await IncidentReport.aggregate(pipeline).to_list()

    @staticmethod
    async def iuu_type_cooccurrence() -> list[dict]:
        """Pairwise co-occurrence of IUUTypes within the same incident.

        Returns rows {"a": typeA, "b": typeB, "count": n}. The diagonal
        (a == b) counts incidents that include that type at all; off-diagonal
        is symmetric (both (a,b) and (b,a) emitted).
        """
        from collections import Counter

        pipeline = [
            {
                "$project": {
                    "types": "$incident_classification.iuuClassifications.IUUType"
                }
            }
        ]
        rows = await IncidentReport.aggregate(pipeline).to_list()

        pair_counts: Counter = Counter()
        for row in rows:
            types = row.get("types") or []
            uniq = sorted({t for t in types if t})
            for a in uniq:
                pair_counts[(a, a)] += 1
            for i, a in enumerate(uniq):
                for b in uniq[i + 1 :]:
                    pair_counts[(a, b)] += 1
                    pair_counts[(b, a)] += 1
        return [{"a": a, "b": b, "count": n} for (a, b), n in pair_counts.items()]

    @staticmethod
    async def iuu_subtype_cooccurrence() -> dict:
        """Per-IUU-type subtype co-occurrence.

        Returns {iuu_type: [{"a": subtypeA, "b": subtypeB, "count": n}, ...]}.
        Diagonal (a == b) counts incidents that include that subtype at all
        under this IUUType. Off-diagonal is symmetric.
        """
        from collections import Counter

        pipeline = [
            {"$unwind": "$incident_classification.iuuClassifications"},
            {
                "$project": {
                    "iuu_type": "$incident_classification.iuuClassifications.IUUType",
                    "subtypes": "$incident_classification.iuuClassifications.IUUSubType",
                }
            },
        ]
        rows = await IncidentReport.aggregate(pipeline).to_list()

        per_type: dict[str, Counter] = {}
        for row in rows:
            iuu_type = row.get("iuu_type")
            subs = row.get("subtypes") or []
            uniq = sorted({s for s in subs if s})
            if not iuu_type or not uniq:
                continue
            counter = per_type.setdefault(iuu_type, Counter())
            for a in uniq:
                counter[(a, a)] += 1
            for i, a in enumerate(uniq):
                for b in uniq[i + 1 :]:
                    counter[(a, b)] += 1
                    counter[(b, a)] += 1

        return {
            iuu_type: [{"a": a, "b": b, "count": n} for (a, b), n in counter.items()]
            for iuu_type, counter in per_type.items()
        }

    @staticmethod
    async def kde_fill_rate_per_incident(
        exclude: set[str] | None = None,
        iuu_type: str | None = None,
    ) -> dict:
        """Per-incident KDE fill rate over ExtractedIncidentData fields.

        Returns {"total_fields": N, "rates": [r1, r2, ...], "counts": [c1, ...]}
        where each entry corresponds to one incident. Fields in ``exclude``
        are dropped from both the numerator and the denominator.
        """

        def _is_list_field(annotation) -> bool:
            if get_origin(annotation) is list:
                return True
            for arg in get_args(annotation):
                if get_origin(arg) is list:
                    return True
            return False

        exclude = exclude or set()
        list_fields = {
            name
            for name, info in ExtractedIncidentData.model_fields.items()
            if _is_list_field(info.annotation)
        }
        fields = [
            f for f in ExtractedIncidentData.model_fields.keys() if f not in exclude
        ]
        total_fields = len(fields)

        def _present_expr(field: str) -> dict:
            path = f"$extracted_information.{field}"
            if field in list_fields:
                return {
                    "$cond": [
                        {"$gt": [{"$size": {"$ifNull": [path, []]}}, 0]},
                        1,
                        0,
                    ]
                }
            return {"$cond": [{"$gt": [path, None]}, 1, 0]}

        pipeline: list[dict] = []
        if iuu_type and iuu_type != "all":
            pipeline.append(
                {
                    "$match": {
                        "incident_classification.iuuClassifications": {
                            "$elemMatch": {"IUUType": iuu_type}
                        }
                    }
                }
            )
        pipeline.append(
            {"$project": {"filled": {"$add": [_present_expr(f) for f in fields]}}}
        )
        rows = await IncidentReport.aggregate(pipeline).to_list()
        counts = [int(r.get("filled", 0)) for r in rows]
        rates = [round(c / total_fields, 4) if total_fields else 0.0 for c in counts]
        return {
            "total_fields": total_fields,
            "counts": counts,
            "rates": rates,
        }

    @staticmethod
    async def avg_leaf_field_count(
        iuu_type: str | None = None,
        exclude_keys: set[str] | None = None,
    ) -> dict:
        """Average number of populated leaf fields per incident.

        A "leaf" is any scalar (str/int/float/bool) attribute in the
        ``ExtractedIncidentData`` tree, including those inside nested
        submodels and inside elements of list-of-submodel fields. A leaf
        counts as populated when its value is not None and not an empty
        string/list/dict. Verification booleans (``verified``/``validated``)
        are excluded by default.

        Args:
            iuu_type: Optional. If set, only incidents whose
                ``incident_classification.iuuClassifications.IUUType``
                includes this value are considered.
            exclude_keys: Field names to skip at any depth.

        Returns:
            ``{"incidents": N, "mean": x, "median": y, "min": a, "max": b,
              "total_possible_leaves": L, "counts": [...]}``
        """
        exclude_keys = exclude_keys or {"verified", "validated"}

        def _count_possible_leaves(model_cls) -> int:
            total = 0
            for name, info in model_cls.model_fields.items():
                if name in exclude_keys:
                    continue
                ann = info.annotation
                inner = _unwrap_optional(ann)
                if _is_basemodel(inner):
                    total += _count_possible_leaves(inner)
                elif get_origin(inner) is list:
                    (item_t,) = get_args(inner) or (None,)
                    item_t = _unwrap_optional(item_t)
                    if _is_basemodel(item_t):
                        total += _count_possible_leaves(item_t)
                    else:
                        total += 1
                else:
                    total += 1
            return total

        def _unwrap_optional(ann):
            if ann is None:
                return ann
            args = [a for a in get_args(ann) if a is not type(None)]  # noqa: E721
            if get_origin(ann) is not None and args and get_origin(ann) is not list:
                return args[0] if len(args) == 1 else ann
            return ann

        def _is_basemodel(t) -> bool:
            try:
                from pydantic import BaseModel

                return isinstance(t, type) and issubclass(t, BaseModel)
            except Exception:
                return False

        def _is_populated_leaf(v) -> bool:
            if v is None:
                return False
            if isinstance(v, str):
                return v.strip() != ""
            if isinstance(v, (list, dict)):
                return len(v) > 0
            return True

        def _count_filled_leaves(value, model_cls) -> int:
            if value is None or not isinstance(value, dict):
                return 0
            filled = 0
            for name, info in model_cls.model_fields.items():
                if name in exclude_keys:
                    continue
                ann = info.annotation
                inner = _unwrap_optional(ann)
                v = value.get(name)
                if _is_basemodel(inner):
                    filled += _count_filled_leaves(v, inner)
                elif get_origin(inner) is list:
                    (item_t,) = get_args(inner) or (None,)
                    item_t = _unwrap_optional(item_t)
                    if _is_basemodel(item_t):
                        if isinstance(v, list):
                            for item in v:
                                filled += _count_filled_leaves(item, item_t)
                    else:
                        if _is_populated_leaf(v):
                            filled += 1
                else:
                    if _is_populated_leaf(v):
                        filled += 1
            return filled

        total_possible = _count_possible_leaves(ExtractedIncidentData)

        match: dict = {}
        if iuu_type:
            match["incident_classification.iuuClassifications.IUUType"] = iuu_type

        pipeline = []
        if match:
            pipeline.append({"$match": match})
        pipeline.append({"$project": {"extracted_information": 1}})

        rows = await IncidentReport.aggregate(pipeline).to_list()
        counts = [
            _count_filled_leaves(r.get("extracted_information"), ExtractedIncidentData)
            for r in rows
        ]

        n = len(counts)
        if n == 0:
            return {
                "incidents": 0,
                "mean": 0.0,
                "median": 0.0,
                "min": 0,
                "max": 0,
                "total_possible_leaves": total_possible,
                "counts": [],
            }

        sorted_counts = sorted(counts)
        mid = n // 2
        median = (
            sorted_counts[mid]
            if n % 2
            else (sorted_counts[mid - 1] + sorted_counts[mid]) / 2
        )
        return {
            "incidents": n,
            "mean": round(sum(counts) / n, 3),
            "median": median,
            "min": min(counts),
            "max": max(counts),
            "total_possible_leaves": total_possible,
            "counts": counts,
        }

    @staticmethod
    async def leaf_presence_matrix(
        exclude_keys: set[str] | None = None,
    ) -> dict:
        """Per-incident 0/1 presence vector over ExtractedIncidentData leaves.

        List-of-anything fields are treated as one leaf (presence = list
        non-empty). Nested BaseModels expand to dotted paths. Verification
        booleans are excluded by default. Intended for biclustering.

        Returns:
            ``{"leaf_paths": [...], "incidents": [
                {"id": str, "iuu_types": [...], "presence": [0|1, ...]}
            ]}``
        """
        exclude_keys = exclude_keys or {"verified", "validated"}

        def _unwrap_optional(ann):
            if ann is None:
                return ann
            args = [a for a in get_args(ann) if a is not type(None)]  # noqa: E721
            if get_origin(ann) is not None and args and get_origin(ann) is not list:
                return args[0] if len(args) == 1 else ann
            return ann

        def _is_basemodel(t) -> bool:
            try:
                from pydantic import BaseModel

                return isinstance(t, type) and issubclass(t, BaseModel)
            except Exception:
                return False

        def _is_populated_leaf(v) -> bool:
            if v is None:
                return False
            if isinstance(v, str):
                return v.strip() != ""
            if isinstance(v, (list, dict)):
                return len(v) > 0
            return True

        def _enumerate_paths(model_cls, prefix: str = "") -> list[str]:
            paths: list[str] = []
            for name, info in model_cls.model_fields.items():
                if name in exclude_keys:
                    continue
                dotted = f"{prefix}.{name}" if prefix else name
                inner = _unwrap_optional(info.annotation)
                if _is_basemodel(inner):
                    paths.extend(_enumerate_paths(inner, dotted))
                else:
                    paths.append(dotted)
            return paths

        def _presence_for(value, model_cls, prefix: str = "") -> dict[str, int]:
            out: dict[str, int] = {}
            if not isinstance(value, dict):
                value = {}
            for name, info in model_cls.model_fields.items():
                if name in exclude_keys:
                    continue
                dotted = f"{prefix}.{name}" if prefix else name
                inner = _unwrap_optional(info.annotation)
                v = value.get(name)
                if _is_basemodel(inner):
                    out.update(_presence_for(v, inner, dotted))
                else:
                    out[dotted] = 1 if _is_populated_leaf(v) else 0
            return out

        leaf_paths = _enumerate_paths(ExtractedIncidentData)

        pipeline = [
            {
                "$project": {
                    "extracted_information": 1,
                    "iuu_types": "$incident_classification.iuuClassifications.IUUType",
                }
            }
        ]
        rows = await IncidentReport.aggregate(pipeline).to_list()

        incidents: list[dict] = []
        for r in rows:
            presence_map = _presence_for(
                r.get("extracted_information"), ExtractedIncidentData
            )
            presence_vec = [presence_map.get(p, 0) for p in leaf_paths]
            incidents.append(
                {
                    "id": str(r.get("_id")),
                    "iuu_types": [t for t in (r.get("iuu_types") or []) if t],
                    "presence": presence_vec,
                }
            )

        return {"leaf_paths": leaf_paths, "incidents": incidents}

    @staticmethod
    async def enforcement_country_by_quarter() -> list[dict]:
        """Counts of incidents grouped by (enforcementCountry, year-quarter).

        Quarter derived from ``eventData.eventDate`` (YYYY-MM-DD). Rows where
        either eventDate or enforcementCountry is missing/"NA" are excluded.
        """
        pipeline = [
            {
                "$match": {
                    "extracted_information.eventData.eventDate": {
                        "$nin": [None, "", "NA"]
                    },
                    "extracted_information.eventData.enforcementCountry": {
                        "$nin": [None, "", "NA"]
                    },
                }
            },
            {
                "$project": {
                    "country": "$extracted_information.eventData.enforcementCountry",
                    "year": {
                        "$substr": [
                            "$extracted_information.eventData.eventDate",
                            0,
                            4,
                        ]
                    },
                    "month": {
                        "$convert": {
                            "input": {
                                "$substr": [
                                    "$extracted_information.eventData.eventDate",
                                    5,
                                    2,
                                ]
                            },
                            "to": "int",
                            "onError": 0,
                            "onNull": 0,
                        }
                    },
                }
            },
            {"$match": {"year": {"$regex": r"^\d{4}$"}, "month": {"$gte": 1}}},
            {
                "$project": {
                    "country": 1,
                    "quarter": {
                        "$concat": [
                            "$year",
                            "-Q",
                            {
                                "$switch": {
                                    "branches": [
                                        {
                                            "case": {"$lte": ["$month", 3]},
                                            "then": "1",
                                        },
                                        {
                                            "case": {"$lte": ["$month", 6]},
                                            "then": "2",
                                        },
                                        {
                                            "case": {"$lte": ["$month", 9]},
                                            "then": "3",
                                        },
                                    ],
                                    "default": "4",
                                }
                            },
                        ]
                    },
                }
            },
            {
                "$group": {
                    "_id": {"country": "$country", "quarter": "$quarter"},
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id.quarter": 1, "_id.country": 1}},
            {
                "$project": {
                    "_id": 0,
                    "country_code": "$_id.country",
                    "quarter": "$_id.quarter",
                    "count": 1,
                }
            },
        ]
        return await IncidentReport.aggregate(pipeline).to_list()
