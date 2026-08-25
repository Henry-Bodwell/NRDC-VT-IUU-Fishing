from datetime import datetime, timezone
from typing import Literal

from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.audit.base import AuditedDocument


ValidationSessionStatus = Literal[
    "IN_PROGRESS",
    "FLAGGED",
    "REPROCESSING_REQUIRED",
    "READY_FOR_REVALIDATION",
    "COMPLETED",
    "RELEASED",
]

ACTIVE_VALIDATION_STATUSES = [
    "IN_PROGRESS",
    "FLAGGED",
    "REPROCESSING_REQUIRED",
    "READY_FOR_REVALIDATION",
]


class ValidationSession(AuditedDocument):
    """Validation lease state for one source."""

    source_id: str = Field(..., description="Source being validated")
    validator_id: str = Field(..., description="User who currently owns the lease")
    status: ValidationSessionStatus = "IN_PROGRESS"
    current_incident_id: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None
    lock_expires_at: datetime
    flag_reason: str | None = None
    task_id: str | None = None
    reviewed_sections: dict[str, list[str]] = Field(default_factory=dict)

    class Settings:
        name = "validation_sessions"
        indexes = [
            "source_id",
            "validator_id",
            "status",
            "lock_expires_at",
            # The index closes the race between simultaneous lease requests.
            IndexModel(
                [("source_id", ASCENDING)],
                unique=True,
                name="one_active_validation_session_per_source",
                partialFilterExpression={
                    "status": {"$in": ACTIVE_VALIDATION_STATUSES}
                },
            ),
        ]
