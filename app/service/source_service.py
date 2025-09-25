import logging

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.models.articles import Source
from app.service.service import Service, _filter_valid_fields

logger = logging.getLogger(__name__)


class SourceService(Service):
    @staticmethod
    async def delete_source(source_id: str) -> bool:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source with ID {source_id} not found",
            )

        try:
            await source.delete()
            logger.info(f"Successfully deleted source {source_id}")
        except Exception as e:
            logger.error(f"Deleted failed for source {source_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete the source.",
            )
        return True

    @staticmethod
    async def update_source(source_id: str, update_data: dict) -> Source:
        return await Service.update_model(
            model_cls=Source,
            model_id=source_id,
            update_data=update_data,
            model_name="source",
        )
