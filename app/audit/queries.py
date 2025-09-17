from datetime import datetime
from typing import Any, Dict, List, Optional
from bson import ObjectId

from app.audit.enums import ChangeType, OperationType
from app.audit.models import AuditLog
from app.audit.strategies import TextDiffStrategy


class AuditQueryService:
    """Service for querying audit history and reconstructing states"""

    @classmethod
    async def get_document_history(
        cls, document_id: ObjectId, limit: int = 100, since: Optional[datetime] = None
    ) -> List[AuditLog]:
        """Get audit history for a specific document"""
        query = {"document_id": document_id}

        if since:
            query["timestamp"] = {"$gte": since}

        return (
            await AuditLog.find(query).sort(-AuditLog.timestamp).limit(limit).to_list()
        )

    @classmethod
    async def get_user_activity(
        cls, user_id: str, document_type: Optional[str] = None, limit: int = 100
    ) -> List[AuditLog]:
        """Get all audit entries for a specific user"""
        query = {"user_id": user_id}

        if document_type:
            query["document_type"] = document_type

        return (
            await AuditLog.find(query).sort(-AuditLog.timestamp).limit(limit).to_list()
        )

    @classmethod
    async def get_system_activity(
        cls,
        since: Optional[datetime] = None,
        document_type: Optional[str] = None,
        operation: Optional[OperationType] = None,
        limit: int = 1000,
    ) -> List[AuditLog]:
        """Get system-wide audit activity"""
        query = {}

        if since:
            query["timestamp"] = {"$gte": since}
        if document_type:
            query["document_type"] = document_type
        if operation:
            query["operation"] = operation

        return (
            await AuditLog.find(query).sort(-AuditLog.timestamp).limit(limit).to_list()
        )

    @classmethod
    async def reconstruct_document_at_version(
        cls,
        document_id: ObjectId,
        target_version: int,
        current_document: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Reconstruct a document's state at a specific version"""
        # Get all changes from target version to current
        changes = (
            await AuditLog.find(
                {"document_id": document_id, "version": {"$gt": target_version}}
            )
            .sort(AuditLog.version)
            .to_list()
        )

        if current_document is None:
            # Would need to fetch current document
            raise ValueError("Current document state required for reconstruction")

        # Apply changes in reverse order
        reconstructed_state = current_document.copy()

        for audit_entry in reversed(changes):
            reconstructed_state = cls._reverse_apply_changes(
                reconstructed_state, audit_entry.changes
            )

        return reconstructed_state

    @classmethod
    def _reverse_apply_changes(
        cls, document_state: Dict[str, Any], changes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Apply audit changes in reverse to reconstruct previous state"""
        # This is complex and depends on change type
        # Implementation would need to handle both JSON patches and text diffs in reverse
        # For now, this is a placeholder that demonstrates the concept

        result = document_state.copy()
        text_diff_strategy = TextDiffStrategy()

        for change in changes:
            field_path = change.get("field_path")
            change_type = change.get("change_type")

            if change_type == ChangeType.TEXT_DIFF:
                # For text diffs, we'd need to store reverse patches or compute them
                # This is a simplified version
                pass
            elif change_type == ChangeType.JSON_PATCH:
                # For JSON patches, we'd need to reverse the patches
                # This requires more complex logic
                pass

        return result
