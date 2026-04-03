import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie import PydanticObjectId
from bson import DBRef

from app.audit.enums import ChangeType, OperationType
from app.audit.models import AuditLog
from app.audit.strategies import TextDiffStrategy

logger = logging.getLogger(__name__)


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert MongoDB types (DBRef, PydanticObjectId) to JSON-safe values."""
    if isinstance(obj, DBRef):
        return str(obj.id)
    if isinstance(obj, PydanticObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    return obj


class AuditQueryService:
    """Service for querying audit history and reconstructing states"""

    @classmethod
    async def get_document_history(
        cls,
        document_id: PydanticObjectId,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[AuditLog]:
        """Get audit history for a specific document"""
        query: Dict[str, Any] = {"document_id": document_id}

        if since:
            query["timestamp"] = {"$gte": since}

        return await AuditLog.find(query).sort("-timestamp").limit(limit).to_list()

    @classmethod
    async def get_user_activity(
        cls, user_id: str, document_type: Optional[str] = None, limit: int = 100
    ) -> List[AuditLog]:
        """Get all audit entries for a specific user"""
        query: Dict[str, Any] = {"user_id": user_id}

        if document_type:
            query["document_type"] = document_type

        return await AuditLog.find(query).sort("-timestamp").limit(limit).to_list()

    @classmethod
    async def get_system_activity(
        cls,
        since: Optional[datetime] = None,
        document_type: Optional[str] = None,
        operation: Optional[OperationType] = None,
        limit: int = 1000,
    ) -> List[AuditLog]:
        """Get system-wide audit activity"""
        query: Dict[str, Any] = {}

        if since:
            query["timestamp"] = {"$gte": since}
        if document_type:
            query["document_type"] = document_type
        if operation:
            query["operation"] = operation

        return await AuditLog.find(query).sort("-timestamp").limit(limit).to_list()

    @classmethod
    async def reconstruct_document_at_version(
        cls,
        document_id: PydanticObjectId,
        target_version: int,
    ) -> Dict[str, Any]:
        """Reconstruct a document's state at a specific version.

        Walk-back approach:
        - For live docs: start from current DB state, reverse diffs backward
        - For deleted docs: start from DELETE log snapshot, reverse diffs backward

        Returns a dict with keys: document_id, document_type, version,
        is_deleted, state, skipped_fields.
        """
        # Find the earliest audit log to confirm this document exists
        create_log = await AuditLog.find_one(
            {"document_id": document_id, "operation": OperationType.CREATE}
        )
        if not create_log:
            raise ValueError(f"No audit history found for document {document_id}")

        document_type = create_log.document_type

        # Check for DELETE log (determines if doc is deleted)
        delete_log = await AuditLog.find_one(
            {"document_id": document_id, "operation": OperationType.DELETE}
        )

        is_deleted = delete_log is not None

        # Determine starting state and max version
        if is_deleted:
            if delete_log.snapshot:
                starting_state = delete_log.snapshot.copy()
                starting_version = delete_log.version
            else:
                # Deleted without snapshot -- try to fetch from DB as fallback
                model_cls = cls._resolve_model_class(document_type)
                doc = await model_cls.get(document_id)
                if not doc:
                    raise ValueError(
                        f"Cannot reconstruct deleted document {document_id}: "
                        f"no snapshot stored and document not in database"
                    )
                starting_state = doc.model_dump(mode="json")
                starting_version = doc.version
        else:
            model_cls = cls._resolve_model_class(document_type)
            doc = await model_cls.get(document_id)
            if not doc:
                raise ValueError(
                    f"Cannot reconstruct document {document_id}: "
                    f"not found in database"
                )
            starting_state = doc.model_dump(mode="json")
            starting_version = doc.version

        # Validate target version
        if target_version < 1 or target_version > starting_version:
            raise ValueError(
                f"Target version must be between 1 and {starting_version}, "
                f"got {target_version}"
            )

        # If requesting the current/latest version, return as-is
        if target_version == starting_version:
            return {
                "document_id": str(document_id),
                "document_type": document_type,
                "version": target_version,
                "is_deleted": is_deleted,
                "state": _sanitize_for_json(starting_state),
                "skipped_fields": [],
            }

        # Fetch UPDATE logs between target_version and starting_version
        # These are the logs whose changes we need to reverse
        update_logs = (
            await AuditLog.find(
                {
                    "document_id": document_id,
                    "operation": OperationType.UPDATE,
                    "version": {
                        "$gt": target_version,
                        "$lte": starting_version,
                    },
                }
            )
            .sort("-version")
            .to_list()
        )

        # Walk back: reverse each log's changes from newest to oldest
        reconstructed = starting_state.copy()
        all_skipped: List[str] = []

        for audit_entry in update_logs:
            reconstructed, skipped = cls._reverse_apply_changes(
                reconstructed, audit_entry.changes
            )
            all_skipped.extend(skipped)

        # Sanitize to convert DBRef/ObjectId/datetime to JSON-safe values
        return {
            "document_id": str(document_id),
            "document_type": document_type,
            "version": target_version,
            "is_deleted": is_deleted,
            "state": _sanitize_for_json(reconstructed),
            "skipped_fields": list(set(all_skipped)),
        }

    @classmethod
    def _reverse_apply_changes(
        cls, document_state: Dict[str, Any], changes: List[Dict[str, Any]]
    ) -> tuple[Dict[str, Any], List[str]]:
        """Apply audit changes in reverse to reconstruct previous state.

        Returns (reconstructed_state, skipped_fields) where skipped_fields
        lists field paths that could not be reversed (e.g. old logs without
        old_value).
        """
        result = document_state.copy()
        skipped: List[str] = []
        text_strategy = TextDiffStrategy()

        for change in changes:
            field_path = change.get("field_path")
            change_type = change.get("change_type")

            # Skip the id field -- audit capture mismatch makes it unreliable
            if field_path == "id":
                continue

            if change_type == ChangeType.JSON_PATCH:
                if "old_value" in change:
                    result[field_path] = change["old_value"]
                else:
                    # Legacy log without old_value -- cannot reverse
                    skipped.append(field_path)
                    logger.warning(
                        f"Cannot reverse JSON_PATCH for '{field_path}': "
                        f"old_value not stored (legacy audit log)"
                    )

            elif change_type == ChangeType.TEXT_DIFF:
                patch_text = change.get("patch_text")
                current_text = result.get(field_path, "")

                if patch_text and isinstance(current_text, str):
                    reversed_patch = text_strategy.reverse_text_patches(patch_text)
                    result[field_path] = text_strategy.reconstruct_text(
                        current_text, reversed_patch
                    )
                else:
                    skipped.append(field_path)
                    logger.warning(
                        f"Cannot reverse TEXT_DIFF for '{field_path}': "
                        f"missing patch_text or non-string field value"
                    )

            elif change_type == ChangeType.REFERENCE_CHANGE:
                old_ids = change.get("old_ids", [])
                result[field_path] = old_ids

        return result, skipped

    @classmethod
    def _resolve_model_class(cls, document_type: str):
        """Resolve a document_type string to its Beanie model class."""
        from app.models.sources import Source
        from app.models.incidents import IncidentReport
        from app.models.overviews import IndustryOverview

        model_map = {
            "Source": Source,
            "IncidentReport": IncidentReport,
            "IndustryOverview": IndustryOverview,
        }
        model_cls = model_map.get(document_type)
        if not model_cls:
            raise ValueError(f"Unknown document type: {document_type}")
        return model_cls
