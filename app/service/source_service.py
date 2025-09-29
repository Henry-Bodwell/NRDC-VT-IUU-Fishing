import logging

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.models.articles import Source
from app.service.service import Service, _filter_valid_fields

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
        return await Service.update_model(
            model_cls=Source,
            model_id=source_id,
            update_data=update_data,
            model_name="source",
        )
