from typing import Dict, Any
import jsondiff
from diff_match_patch import diff_match_patch
from .enums import ChangeType


class AuditStrategy:
    """Base class for different audit strategies"""

    def should_handle(self, old_value: Any, new_value: Any, field_path: str) -> bool:
        raise NotImplementedError

    def compute_changes(
        self, old_value: Any, new_value: Any, field_path: str
    ) -> Dict[str, Any]:
        raise NotImplementedError


class JsonPatchStrategy(AuditStrategy):
    """Standard JSON Patch strategy for structured data"""

    def should_handle(self, old_value: Any, new_value: Any, field_path: str) -> bool:
        # Handle everything except large strings
        if isinstance(old_value, str) and isinstance(new_value, str):
            return max(len(old_value), len(new_value)) <= 1024
        return True

    def compute_changes(
        self, old_value: Any, new_value: Any, field_path: str
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

    def should_handle(self, old_value: Any, new_value: Any, field_path: str) -> bool:
        return (
            isinstance(old_value, str)
            and isinstance(new_value, str)
            and max(len(old_value), len(new_value)) > self.TEXT_DIFF_THRESHOLD
        )

    def compute_changes(
        self, old_value: str, new_value: str, field_path: str
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
