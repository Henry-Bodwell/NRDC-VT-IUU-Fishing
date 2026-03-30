import logging

from app.models.incidents import IncidentReport, IndustryOverview
from app.models.sources import Source, ArticleScopeClassification
from app.service.service import Service
from app.service.incident_service import IncidentService

logger = logging.getLogger(__name__)


class SourceService(Service):
    @staticmethod
    async def delete_source(source_id: str) -> bool:
        return await Service.delete(
            model_cls=Source,
            model_id=source_id,
            model_name="source",
        )

    @staticmethod
    async def update_source(source_id: str, update_data: dict) -> Source:
        """Update a source. If article_scope changes, triggers reclassification.

        Reclassification flow (transaction-safe):
        1. Run re-analysis with new scope (no DB mutations yet)
        2. Only on success: delete/unlink old linked docs, save new results
        3. If analysis fails: nothing is changed
        """
        # Check if article_scope is being changed
        if "article_scope" in update_data:
            new_scope_data = update_data["article_scope"]
            new_scope_type = (
                new_scope_data.get("articleType") if new_scope_data else None
            )

            if new_scope_type:
                source = await Source.get(source_id, fetch_links=False)
                current_scope = (
                    source.article_scope.articleType
                    if source and source.article_scope
                    else None
                )

                if source and current_scope != new_scope_type:
                    return await SourceService._reclassify_source(
                        source, new_scope_type
                    )

        # No scope change -- normal field update
        return await Service.update_model(
            model_cls=Source,
            model_id=source_id,
            update_data=update_data,
            model_name="source",
        )

    @staticmethod
    async def _reclassify_source(source: Source, new_scope: str) -> Source:
        """Reclassify a source: analyze first, then clean up old docs.

        Order of operations (transaction safety):
        1. Run analysis with new scope (if not "Unrelated")
           - If this fails, nothing has been modified
        2. Delete/unlink old linked documents
        3. Save new results
        4. Return refreshed source
        """
        source_id = str(source.id)

        # ---- Step 1: Run analysis BEFORE any cleanup ----
        pipeline_output = None
        if new_scope != "Unrelated to IUU Fishing":
            pipeline_output = await IncidentService.analyze_existing_source(
                source=source,
                assumed_scope=new_scope,
            )

        # ---- Step 2: Clean up old linked incidents ----
        for incident_link in source.incidents or []:
            incident_id = (
                incident_link.ref.id
                if hasattr(incident_link, "ref")
                else incident_link.id
            )
            incident = await IncidentReport.get(incident_id, fetch_links=False)
            if not incident:
                continue

            if len(incident.sources or []) <= 1:
                await incident.delete()
                logger.info(
                    f"Deleted sole-source incident {incident_id} "
                    f"during reclassification of source {source_id}"
                )
            else:
                await incident.remove_source(source)
                logger.info(
                    f"Unlinked source {source_id} "
                    f"from shared incident {incident_id}"
                )

        # ---- Step 3: Clean up linked overview ----
        if source.overview:
            overview_id = (
                source.overview.ref.id
                if hasattr(source.overview, "ref")
                else source.overview.id
            )
            overview = await IndustryOverview.get(overview_id)
            if overview:
                await overview.delete()
                logger.info(
                    f"Deleted overview {overview_id} "
                    f"during reclassification of source {source_id}"
                )

        # ---- Step 4: Clear stale references ----
        source.incidents = []
        source.overview = None

        # ---- Step 5: Save new results ----
        if new_scope == "Unrelated to IUU Fishing":
            source.article_scope = ArticleScopeClassification(
                articleType=new_scope, confidence=1.0
            )
            await source.save()
        else:
            await IncidentService.save_pipeline_output(pipeline_output)

        # Re-fetch for clean serializable state
        return await Source.get(str(source.id), fetch_links=False)
