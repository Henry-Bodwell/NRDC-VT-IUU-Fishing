from typing import Dict, List, Any, Optional
from beanie import Document
from .models import AuditLog
from .strategies import (
    AuditStrategy,
    JsonPatchStrategy,
    TextDiffStrategy,
    ReferenceTrackingStrategy,
)
from .enums import OperationType, ChangeType
from .context import AuditContext


class AuditService:
    """Central service for managing audit operations"""

    FIELD_HANDLING_CONFIG = {
        "IncidentReport": {
            "excluded": [],
            "reference_only": ["sources", "primary_source"],
            "full_audit": [],
        },
        "Source": {
            "excluded": [],
            "reference_only": ["incidents", "overview"],
            "full_audit": [],
        },
        "IndustryOverview": {
            "excluded": [],
            "reference_only": ["source"],
            "full_audit": [],
        },
    }

    def __init__(self):
        self.reference_strategy = ReferenceTrackingStrategy(
            {
                doc_type: config["reference_only"]
                for doc_type, config in self.FIELD_HANDLING_CONFIG.items()
            }
        )

        self.strategies: List[AuditStrategy] = [
            self.reference_strategy,  # Check reference fields first
            TextDiffStrategy(),  # Then large text
            JsonPatchStrategy(),  # Fallback for everything else
        ]

    @classmethod
    def _get_instance(cls):
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance

    @classmethod
    async def log_create(cls, document: Document) -> AuditLog:
        """Log document creation"""
        audit_entry = AuditLog(
            document_id=document.id,
            document_type=document.__class__.__name__,
            version=1,
            operation=OperationType.CREATE,
            user_id=AuditContext.get_user(),
            changes=[],  # No changes for creation
            change_summary={"fields_created": len(document.model_dump())},
        )

        await audit_entry.insert()
        return audit_entry

    @classmethod
    async def log_update(
        cls, document: Document, original_state: Dict[str, Any]
    ) -> Optional[AuditLog]:
        """Log document updates with field-level change detection"""
        current_state = document.model_dump(exclude={"id", "_original_state"})
        document_type = document.__class__.__name__

        service = cls._get_instance()

        # Detect changes
        changes = service._detect_changes(original_state, current_state, document_type)

        if not changes:
            return None  # No changes detected

        # Get current version (assuming document has version field)
        current_version = getattr(document, "version", 1)

        # Create change summary
        change_summary = cls._create_change_summary(changes)

        audit_entry = AuditLog(
            document_id=document.id,
            document_type=document_type,
            version=current_version,
            operation=OperationType.UPDATE,
            user_id=AuditContext.get_user(),
            changes=changes,
            change_summary=change_summary,
        )

        await audit_entry.insert()
        return audit_entry

    @classmethod
    async def log_delete(cls, document: Document) -> AuditLog:
        """Log document deletion"""
        current_version = getattr(document, "version", 1)

        audit_entry = AuditLog(
            document_id=document.id,
            document_type=document.__class__.__name__,
            version=current_version,
            operation=OperationType.DELETE,
            user_id=AuditContext.get_user(),
            changes=[],
            change_summary={"operation": "delete"},
        )

        await audit_entry.insert()
        return audit_entry

    def _detect_changes(
        self, old_state: Dict[str, Any], new_state: Dict[str, Any], document_type: str
    ) -> List[Dict[str, Any]]:
        """Detect and categorize changes between two document states"""
        changes = []

        config = self.FIELD_HANDLING_CONFIG.get(document_type, {})
        excluded_fields = set(config.get("excluded", []))

        # Get all fields that might have changed
        all_fields = set(old_state.keys()) | set(new_state.keys())

        for field_name in all_fields:
            if field_name in excluded_fields:
                continue  # Skip excluded fields

            old_value = old_state.get(field_name)
            new_value = new_state.get(field_name)

            # Skip if values are identical
            if old_value == new_value:
                continue

            # Findt appropriate strategy and compue changes
            strategy = self._select_strategy(
                old_value, new_value, field_name, document_type
            )
            change_data = strategy.compute_changes(
                old_value, new_value, field_name, document_type
            )
            changes.append(change_data)

        return changes

    def _select_strategy(
        self, old_value: Any, new_value: Any, field_path: str, document_type: str
    ) -> AuditStrategy:
        """Select the appropriate audit strategy for the given field change"""
        for strategy in self.strategies:
            if hasattr(strategy, "should_handle"):
                if strategy.__class__.__name__ == "ReferenceTrackingStrategy":
                    if strategy.should_handle(
                        old_value, new_value, field_path, document_type
                    ):
                        return strategy
                else:
                    if strategy.should_handle(old_value, new_value, field_path):
                        return strategy

        # Fallback to JSON patch
        return self.strategies[-1]

    @classmethod
    def _create_change_summary(cls, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create summary statistics for the changes"""
        summary = {
            "total_fields_changed": len(changes),
            "json_patch_changes": len(
                [c for c in changes if c.get("change_type") == ChangeType.JSON_PATCH]
            ),
            "text_diff_changes": len(
                [c for c in changes if c.get("change_type") == ChangeType.TEXT_DIFF]
            ),
            "reference_changes": len(
                [
                    c
                    for c in changes
                    if c.get("change_type") == ChangeType.REFERENCE_CHANGE
                ]
            ),
            "total_size_impact": 0,
        }

        # Calculate storage efficiency
        for change in changes:
            if change.get("change_type") == ChangeType.TEXT_DIFF:
                old_size = change.get("old_size", 0)
                patch_size = change.get("patch_size", 0)
                summary["total_size_impact"] += patch_size - old_size

        return summary
