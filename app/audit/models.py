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

    # Full document snapshot -- only populated on DELETE operations
    snapshot: Optional[Dict[str, Any]] = None

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

    def get_reference_changes(self) -> List[Dict[str, Any]]:
        """Extract reference changes from the changes list"""
        return [
            change
            for change in self.changes
            if change.get("change_type") == ChangeType.REFERENCE_CHANGE
        ]

    def get_added_references(self) -> Dict[str, List[str]]:
        """Get a mapping of field paths to lists of added reference IDs"""
        added_refs = {}
        for change in self.get_reference_changes():
            field_path = change.get("field_path")
            added = change.get("added_references", [])
            if field_path and added:
                added_refs[field_path] = added
        return added_refs

    def get_removed_references(self) -> Dict[str, List[str]]:
        """Get a mapping of field paths to lists of removed reference IDs"""
        removed_refs = {}
        for change in self.get_reference_changes():
            field_path = change.get("field_path")
            removed = change.get("removed_references", [])
            if field_path and removed:
                removed_refs[field_path] = removed
        return removed_refs
