"""
Task status tracking for long-running operations.
"""

from datetime import datetime
from typing import Literal, Optional
from beanie import Document
from pydantic import Field
import uuid


class TaskStatus(Document):
    """
    Tracks status of long-running background tasks (e.g., incident analysis pipeline).

    Tasks are automatically cleaned up 24 hours after completion/failure.
    """

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: Literal["pending", "processing", "completed", "failed"] = Field(
        default="pending"
    )  # "pending", "processing", "completed", "failed"
    task_type: str  # "incident_analysis", etc.

    # Progress tracking
    progress: Optional[dict] = None  # {"stage": "content_extraction", "percent": 30}

    # Results and errors
    result: Optional[dict] = None  # Final PipelineOutput data when completed
    error: Optional[str] = None  # Error message if failed

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    user_id: Optional[str] = None

    # Input parameters (for debugging/retry)
    input_params: Optional[dict] = None

    class Settings:
        name = "tasks"
        indexes = ["task_id", "status", "created_at", "user_id"]

    async def update_progress(self, stage: str, percent: int):
        """Update task progress."""
        self.progress = {"stage": stage, "percent": percent}
        self.status = "processing"
        self.updated_at = datetime.utcnow()
        await self.save()

    async def mark_completed(self, result: dict):
        """Mark task as completed with result."""
        self.status = "completed"
        self.result = result
        self.progress = {"stage": "completed", "percent": 100}
        self.updated_at = datetime.utcnow()
        await self.save()

    async def mark_failed(self, error: str):
        """Mark task as failed with error message."""
        self.status = "failed"
        self.error = error
        self.updated_at = datetime.utcnow()
        await self.save()
