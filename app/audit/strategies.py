from typing import Dict, Any, List
import jsondiff
from diff_match_patch import diff_match_patch
from .enums import ChangeType


class AuditStrategy:
    """Base class for different audit strategies"""

    def should_handle(
        self, old_value: Any, new_value: Any, field_path: str, document_type=None
    ) -> bool:
        raise NotImplementedError

    def compute_changes(
        self, old_value: Any, new_value: Any, field_path: str, document_type=None
    ) -> Dict[str, Any]:
        raise NotImplementedError


class JsonPatchStrategy(AuditStrategy):
    """Standard JSON Patch strategy for structured data"""

    def should_handle(
        self, old_value: Any, new_value: Any, field_path: str, document_type=None
    ) -> bool:
        # Handle everything except large strings
        if isinstance(old_value, str) and isinstance(new_value, str):
            return max(len(old_value), len(new_value)) <= 1024
        return True

    def compute_changes(
        self, old_value: Any, new_value: Any, field_path: str, document_type: str = None
    ) -> Dict[str, Any]:
        # Create minimal objects for jsondiff
        old_obj = {field_path.split(".")[-1]: old_value}
        new_obj = {field_path.split(".")[-1]: new_value}

        patches = jsondiff.diff(old_obj, new_obj)

        return {
            "change_type": ChangeType.JSON_PATCH,
            "field_path": field_path,
            "patches": patches if patches else [],
            "old_value_size": len(str(old_value)) if old_value is not None else 0,
            "new_value_size": len(str(new_value)) if new_value is not None else 0,
        }


class TextDiffStrategy(AuditStrategy):
    """Text-level diffing strategy for large strings"""

    TEXT_DIFF_THRESHOLD = 1024

    def __init__(self):
        self.dmp = diff_match_patch()
        # Configure for efficiency
        self.dmp.Diff_Timeout = 1.0  # 1 second timeout
        self.dmp.Diff_EditCost = 4  # Balance between accuracy and performance

    def should_handle(
        self, old_value: Any, new_value: Any, field_path: str, document_type: str = None
    ) -> bool:
        return (
            isinstance(old_value, str)
            and isinstance(new_value, str)
            and max(len(old_value), len(new_value)) > self.TEXT_DIFF_THRESHOLD
        )

    def compute_changes(
        self, old_value: str, new_value: str, field_path: str, document_type: str = None
    ) -> Dict[str, Any]:
        # Compute character-level patches
        patches = self.dmp.patch_make(old_value, new_value)
        patch_text = self.dmp.patch_toText(patches)

        # Calculate efficiency metrics
        old_size = len(old_value)
        new_size = len(new_value)
        patch_size = len(patch_text)

        return {
            "change_type": ChangeType.TEXT_DIFF,
            "field_path": field_path,
            "patch_text": patch_text,
            "old_size": old_size,
            "new_size": new_size,
            "patch_size": patch_size,
            "compression_ratio": (
                patch_size / max(old_size, new_size)
                if max(old_size, new_size) > 0
                else 0
            ),
        }

    def reconstruct_text(self, original_text: str, patch_text: str) -> str:
        """Reconstruct text from original + patches"""
        patches = self.dmp.patch_fromText(patch_text)
        result = self.dmp.patch_apply(patches, original_text)
        return result[0]  # Returns tuple (text, success_array)


class ReferenceTrackingStrategy(AuditStrategy):
    """Strategy for tracking only IDs of referenced objects"""

    def __init__(self, reference_fields_config: Dict[str, List[str]]):
        self.reference_fields_config = reference_fields_config

    def should_handle(
        self, old_value: Any, new_value: Any, field_path: str, document_type: str = None
    ) -> bool:
        """Check if this field should be handled as a reference field"""
        if not document_type:
            return False

        reference_fields = self.reference_fields_config.get(document_type, [])
        return field_path in reference_fields

    def compute_changes(
        self, old_value: Any, new_value: Any, field_path: str, document_type: str = None
    ) -> Dict[str, Any]:
        old_ids = self._extract_ids(old_value)
        new_ids = self._extract_ids(new_value)

        added_ids = list(set(new_ids) - set(old_ids))
        removed_ids = list(set(old_ids) - set(new_ids))

        return {
            "change_type": ChangeType.REFERENCE,
            "field_path": field_path,
            "old_ids": old_ids,
            "new_ids": new_ids,
            "added_references": added_ids,
            "removed_references": removed_ids,
            "reference_count_change": len(new_ids) - len(old_ids),
        }

    def _extract_ids(self, value: Any) -> List[str]:
        """Extract IDs from embedded objects or lists of objects"""
        if value is None:
            return []
        if isinstance(value, list):
            ids = []
            for item in value:
                if isinstance(item, dict):
                    item_id = item.get("id") or item.get("_id")
                    if item_id:
                        ids.append(str(item_id))

                elif hasattr(item, "id"):
                    ids.append(str(getattr(item, "id")))
            return ids

        elif isinstance(value, dict):
            item_id = value.get("id") or value.get("_id")
            return [str(item_id)] if item_id else []
        elif hasattr(value, "id"):
            return [str(getattr(value, "id"))]
        return []
