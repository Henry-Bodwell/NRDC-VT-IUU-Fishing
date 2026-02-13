import logging


from app.models.sources import Source
from app.models.incidents import IndustryOverview
from app.service.service import Service

logger = logging.getLogger(__name__)


class OverviewService(Service):
    @staticmethod
    async def delete_overview(overview_id: str) -> bool:
        return await Service.delete(
            model_cls=IndustryOverview,
            model_id=overview_id,
            model_name="industry_overviews",
        )

    @staticmethod
    async def update_overview(overview_id: str, update_data: dict) -> Source:
        return await Service.update_model(
            model_cls=IndustryOverview,
            model_id=overview_id,
            update_data=update_data,
            model_name="industry_overviews",
        )
