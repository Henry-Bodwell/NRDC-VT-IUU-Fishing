import logging
from typing import Optional, Type, TypeVar

from beanie import PydanticObjectId
from fastapi import HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def valid_response(response: Optional[T], pydanticModel: Type[T]):
    """
    Helper function to throw an exception if the response is not valid.
    """
    if not response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "not_found",
                "message": f"{pydanticModel.__name__} not found",
            },
        )

    if not isinstance(response, pydanticModel):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "invalid_response",
                "message": f"Expected {pydanticModel.__name__}, got {type(response).__name__}",
            },
        )


def valid_object_id(value: str) -> None:
    """Raise HTTP 400 if value is not a valid MongoDB ObjectId."""
    if not PydanticObjectId.is_valid(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ID format: {value}",
        )


def get_limiter():
    from app.main import limiter

    return limiter
