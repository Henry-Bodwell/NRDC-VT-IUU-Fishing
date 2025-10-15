from typing import Type, TypeVar, Union
from pydantic import ValidationError, BaseModel
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)
T = TypeVar("T")


class Service:
    @staticmethod
    def deep_merge(existing_dict: dict, update_dict: dict) -> dict:
        """Recursively merge update_dict into existing_dict."""
        result = existing_dict.copy()
        for key, value in update_dict.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = Service.deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    async def delete(
        model_cls: Type[T],
        model_id: str,
        model_name: str,
    ) -> bool:
        instance = await model_cls.get(model_id)
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{model_name} with ID {model_id} not found",
            )

        try:
            await instance.delete()
            logger.info(f"Successfully deleted {model_name} {model_id}")
        except Exception as e:
            logger.error(f"Deleted failed for {model_name} {model_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete the {model_name}.",
            )
        return True

    @staticmethod
    async def update_model(
        model_cls: Type[T],
        model_id: str,
        update_data: dict,
        model_name: str,
    ) -> T:
        logger.info(f"Updating {model_name} {model_id} with data: {update_data}")

        # Get the instance with links
        instance = await model_cls.get(model_id, fetch_links=True)
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{model_name.capitalize()} with ID {model_id} not found.",
            )

        # Filter to only valid fields
        updates = _filter_valid_fields(model_cls, update_data)
        if not updates:
            logger.warning(f"No valid fields to update for {model_name} {model_id}")

        # Apply updates by recursively merging nested dicts
        for field, value in updates.items():
            current_value = getattr(instance, field, None)

            # Convert Pydantic models to dicts for merging
            if isinstance(current_value, BaseModel):
                current_dict = current_value.model_dump()
            elif isinstance(current_value, dict):
                current_dict = current_value
            else:
                current_dict = None

            # If both current and new values are dicts, deep merge them
            if current_dict is not None and isinstance(value, dict):
                merged_value = Service.deep_merge(current_dict, value)
                setattr(instance, field, merged_value)
            else:
                # Otherwise, directly set the value
                setattr(instance, field, value)

        try:
            await instance.replace()
            logger.info(f"Successfully updated {model_name} {model_id}")
        except ValidationError as ve:
            logger.error(f"Validation error for {model_name} {model_id}: {ve}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Validation error: {ve}",
            )
        except Exception as e:
            logger.error(f"Update failed for {model_name} {model_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update the {model_name}.",
            )

        return instance


def _filter_valid_fields(model_class, updates: dict) -> dict:
    valid_fields = set(model_class.model_fields.keys())
    return {k: v for k, v in updates.items() if k in valid_fields}
