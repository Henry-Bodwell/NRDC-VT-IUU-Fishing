from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from beanie import Document, PydanticObjectId
from pymongo import IndexModel, ASCENDING, DESCENDING
from pydantic import Field
from .enums import OperationType, ChangeType


class AuditLog(Document):
    """Polymorphic audit log for all document types"""

    # Document identification
    document_id: PydanticObjectId
    document_type: str

    # Change tracking
    version: int
    operation: OperationType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: Optional[str] = None

    # Change data (polymorphic)
    changes: List[Dict[str, Any]] = Field(default_factory=list)
    change_summary: Optional[Dict[str, Any]] = None

    class Settings:
        name = "audit_logs"
        indexes = [
            IndexModel([("document_id", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("document_type", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("user_id", ASCENDING), ("timestamp", DESCENDING)]),
            IndexModel([("timestamp", DESCENDING)]),
        ]

    def get_field_changes(self) -> Dict[str, Dict[str, Any]]:
        """Extract field-level changes for easy access"""
        field_changes = {}
        for change in self.changes:
            field_path = change.get("field_path")
            if field_path:
                field_changes[field_path] = change
        return field_changes
