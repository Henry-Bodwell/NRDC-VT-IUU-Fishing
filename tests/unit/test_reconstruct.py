"""
Unit tests for document state reconstruction via walk-back.

Tests the ability to reconstruct previous document states by starting from
the current state (or DELETE snapshot) and reversing audit log diffs backward.

Covers:
- _reverse_apply_changes for all three change types (JSON_PATCH, TEXT_DIFF, REFERENCE_CHANGE)
- reconstruct_document_at_version for live documents
- reconstruct_document_at_version for deleted documents (via snapshot)
- Multi-version walk-back
- Edge cases: version 1, current version, invalid versions
- Backward compatibility: old logs missing old_value (partial reconstruction)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from beanie import PydanticObjectId

from bson import DBRef

from app.audit.enums import ChangeType, OperationType
from app.audit.models import AuditLog
from app.audit.queries import AuditQueryService
from app.audit.strategies import TextDiffStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_DOC_ID = PydanticObjectId()


def _make_json_patch_change(field_path, old_value, patches=None):
    """Build a JSON_PATCH change entry with old_value (new-style)."""
    return {
        "change_type": ChangeType.JSON_PATCH,
        "field_path": field_path,
        "patches": patches or {},
        "old_value": old_value,
        "old_value_size": len(str(old_value)) if old_value is not None else 0,
        "new_value_size": 0,
    }


def _make_json_patch_change_legacy(field_path, patches=None):
    """Build a JSON_PATCH change entry WITHOUT old_value (old-style log)."""
    return {
        "change_type": ChangeType.JSON_PATCH,
        "field_path": field_path,
        "patches": patches or {},
        "old_value_size": 0,
        "new_value_size": 0,
    }


def _make_text_diff_change(field_path, patch_text, old_size=2000, new_size=2000):
    """Build a TEXT_DIFF change entry."""
    return {
        "change_type": ChangeType.TEXT_DIFF,
        "field_path": field_path,
        "patch_text": patch_text,
        "old_size": old_size,
        "new_size": new_size,
        "patch_size": len(patch_text),
        "compression_ratio": len(patch_text) / max(old_size, new_size),
    }


def _make_reference_change(field_path, old_ids, new_ids):
    """Build a REFERENCE_CHANGE entry."""
    added = list(set(new_ids) - set(old_ids))
    removed = list(set(old_ids) - set(new_ids))
    return {
        "change_type": ChangeType.REFERENCE_CHANGE,
        "field_path": field_path,
        "old_ids": old_ids,
        "new_ids": new_ids,
        "added_references": added,
        "removed_references": removed,
        "reference_count_change": len(new_ids) - len(old_ids),
    }


def _make_audit_log(
    document_id,
    version,
    operation,
    changes=None,
    snapshot=None,
    document_type="Source",
):
    """Build a mock AuditLog."""
    log = MagicMock(spec=AuditLog)
    log.document_id = document_id
    log.document_type = document_type
    log.version = version
    log.operation = operation
    log.changes = changes or []
    log.snapshot = snapshot
    log.change_summary = {}
    return log


def _find_one_for_live_doc(create_log):
    """Build a find_one side_effect that returns create_log for CREATE
    queries and None for DELETE queries (simulating a live document)."""

    async def _side_effect(query, *args, **kwargs):
        if query.get("operation") == OperationType.DELETE:
            return None
        return create_log

    return _side_effect


# ---------------------------------------------------------------------------
# Tests: _reverse_apply_changes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseApplyChanges:
    """Tests for _reverse_apply_changes across all change types."""

    def test_reverse_json_patch_restores_old_value(self):
        """JSON_PATCH with old_value restores the field to its previous value."""
        state = {"status": "modified", "verified": True}
        changes = [_make_json_patch_change("status", "extracted")]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["status"] == "extracted"
        assert result["verified"] is True  # untouched

    def test_reverse_json_patch_restores_none_old_value(self):
        """JSON_PATCH can restore a field to None."""
        state = {"article_title": "Updated Title", "status": "modified"}
        changes = [_make_json_patch_change("article_title", None)]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["article_title"] is None

    def test_reverse_json_patch_restores_dict_old_value(self):
        """JSON_PATCH can restore a nested dict field."""
        state = {
            "article_scope": {"articleType": "Multiple Incidents", "confidence": 0.8}
        }
        old_scope = {"articleType": "Single Incident", "confidence": 0.95}
        changes = [_make_json_patch_change("article_scope", old_scope)]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["article_scope"] == old_scope

    def test_reverse_multiple_json_patches(self):
        """Multiple JSON_PATCH changes reversed in one pass."""
        state = {"status": "modified", "verified": True, "source_type": "ngo"}
        changes = [
            _make_json_patch_change("status", "extracted"),
            _make_json_patch_change("verified", False),
        ]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["status"] == "extracted"
        assert result["verified"] is False
        assert result["source_type"] == "ngo"  # untouched

    def test_reverse_reference_change_restores_old_ids(self):
        """REFERENCE_CHANGE restores the field to old_ids."""
        state = {"sources": ["id2", "id3"]}
        changes = [_make_reference_change("sources", ["id1", "id2"], ["id2", "id3"])]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["sources"] == ["id1", "id2"]

    def test_reverse_reference_change_empty_old_ids(self):
        """REFERENCE_CHANGE can restore to an empty list."""
        state = {"incidents": ["inc1"]}
        changes = [_make_reference_change("incidents", [], ["inc1"])]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["incidents"] == []

    def test_reverse_text_diff_restores_previous_text(self):
        """TEXT_DIFF reversal recovers the original text."""
        strategy = TextDiffStrategy()

        original_text = "Hello World! " * 200
        modified_text = "Hello Universe! " * 200

        # Compute forward patch (original -> modified)
        forward = strategy.compute_changes(original_text, modified_text, "article_text")
        patch_text = forward["patch_text"]

        # State is the modified (newer) version
        state = {"article_text": modified_text}
        changes = [_make_text_diff_change("article_text", patch_text)]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["article_text"] == original_text

    def test_reverse_mixed_change_types(self):
        """All three change types can be reversed in a single pass."""
        strategy = TextDiffStrategy()
        original_text = "Hello World! " * 200
        modified_text = "Hello Universe! " * 200
        forward = strategy.compute_changes(original_text, modified_text, "article_text")

        state = {
            "status": "modified",
            "article_text": modified_text,
            "sources": ["src2"],
        }
        changes = [
            _make_json_patch_change("status", "extracted"),
            _make_text_diff_change("article_text", forward["patch_text"]),
            _make_reference_change("sources", ["src1"], ["src2"]),
        ]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["status"] == "extracted"
        assert result["article_text"] == original_text
        assert result["sources"] == ["src1"]

    def test_reverse_skips_id_field(self):
        """Changes to the 'id' field are skipped during reversal."""
        state = {"id": "current_id", "status": "modified"}
        changes = [_make_json_patch_change("id", "old_id")]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        # id should remain unchanged
        assert result["id"] == "current_id"


# ---------------------------------------------------------------------------
# Tests: Backward compatibility (old logs without old_value)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLegacyLogCompatibility:
    """Tests for handling old audit logs that lack old_value."""

    def test_legacy_json_patch_skipped_gracefully(self):
        """Old JSON_PATCH without old_value is skipped; other fields still work."""
        state = {"status": "modified", "verified": True}
        changes = [
            _make_json_patch_change_legacy("status"),  # no old_value
            _make_json_patch_change("verified", False),  # has old_value
        ]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        # status could not be reversed (no old_value) -- stays as-is
        assert result["status"] == "modified"
        # verified was reversed successfully
        assert result["verified"] is False

    def test_legacy_json_patch_returns_skipped_fields(self):
        """When old_value is missing, the field path should appear in
        skipped_fields if the method tracks them."""
        state = {"status": "modified", "title": "New"}
        changes = [
            _make_json_patch_change_legacy("status"),
            _make_json_patch_change_legacy("title"),
        ]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        # Both fields stay unchanged since neither has old_value
        assert result["status"] == "modified"
        assert result["title"] == "New"

    def test_legacy_reference_change_still_works(self):
        """REFERENCE_CHANGE always has old_ids, so it works regardless of age."""
        state = {"sources": ["new_src"]}
        changes = [_make_reference_change("sources", ["old_src"], ["new_src"])]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["sources"] == ["old_src"]

    def test_mixed_legacy_and_new_changes(self):
        """Mix of old-style and new-style changes in one log."""
        state = {
            "status": "modified",
            "verified": True,
            "source_type": "ngo",
            "sources": ["src2"],
        }
        changes = [
            _make_json_patch_change_legacy("status"),  # old-style, skipped
            _make_json_patch_change("verified", False),  # new-style, reversed
            _make_json_patch_change("source_type", "news"),  # new-style, reversed
            _make_reference_change("sources", ["src1"], ["src2"]),  # always works
        ]

        result, skipped = AuditQueryService._reverse_apply_changes(state, changes)

        assert result["status"] == "modified"  # not reversed
        assert result["verified"] is False
        assert result["source_type"] == "news"
        assert result["sources"] == ["src1"]


# ---------------------------------------------------------------------------
# Tests: reconstruct_document_at_version (live documents)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReconstructLiveDocument:
    """Tests for reconstructing versions of documents still in the database."""

    @pytest.mark.asyncio
    async def test_reconstruct_current_version_returns_current_state(self):
        """Requesting the current version returns the doc as-is."""
        doc_id = PydanticObjectId()
        current_state = {"status": "modified", "version": 3}

        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        mock_doc = MagicMock()
        mock_doc.model_dump.return_value = {**current_state, "id": doc_id}
        mock_doc.version = 3

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=_find_one_for_live_doc(create_log),
            ),
            patch(
                "app.audit.queries.AuditQueryService._resolve_model_class",
                return_value=MagicMock(
                    get=AsyncMock(return_value=mock_doc),
                ),
            ),
            patch.object(
                AuditLog,
                "find",
                return_value=MagicMock(
                    sort=MagicMock(
                        return_value=MagicMock(
                            to_list=AsyncMock(return_value=[]),
                        )
                    )
                ),
            ),
        ):
            result = await AuditQueryService.reconstruct_document_at_version(
                document_id=doc_id,
                target_version=3,
            )

            assert result["version"] == 3
            assert result["state"]["status"] == "modified"
            assert result["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_reconstruct_current_version_sanitizes_dbrefs(self):
        """DBRef and ObjectId in model_dump output are converted to strings."""
        doc_id = PydanticObjectId()
        ref_id = PydanticObjectId()
        overview_ref = DBRef("IndustryOverview", ref_id)

        current_state = {
            "id": doc_id,
            "status": "modified",
            "version": 11,
            "incidents": [
                DBRef("IncidentReport", PydanticObjectId()),
                DBRef("IncidentReport", PydanticObjectId()),
            ],
            "overview": overview_ref,
        }

        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        mock_doc = MagicMock()
        mock_doc.model_dump.return_value = current_state
        mock_doc.version = 11

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=_find_one_for_live_doc(create_log),
            ),
            patch(
                "app.audit.queries.AuditQueryService._resolve_model_class",
                return_value=MagicMock(
                    get=AsyncMock(return_value=mock_doc),
                ),
            ),
        ):
            result = await AuditQueryService.reconstruct_document_at_version(
                document_id=doc_id,
                target_version=11,
            )

            state = result["state"]
            # DBRefs converted to string IDs
            assert all(isinstance(i, str) for i in state["incidents"])
            assert isinstance(state["overview"], str)
            assert state["overview"] == str(ref_id)
            # ObjectId converted to string
            assert isinstance(state["id"], str)
            assert state["id"] == str(doc_id)

    @pytest.mark.asyncio
    async def test_reconstruct_version_1_walks_back_all_updates(self):
        """Walking back to version 1 reverses all UPDATE logs."""
        doc_id = PydanticObjectId()
        current_state = {
            "id": doc_id,
            "status": "modified",
            "verified": True,
            "version": 3,
        }

        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        # Version 2: status changed from "extracted" to "modified"
        update_v2 = _make_audit_log(
            doc_id,
            2,
            OperationType.UPDATE,
            changes=[_make_json_patch_change("status", "extracted")],
        )
        # Version 3: verified changed from False to True
        update_v3 = _make_audit_log(
            doc_id,
            3,
            OperationType.UPDATE,
            changes=[_make_json_patch_change("verified", False)],
        )

        mock_doc = MagicMock()
        mock_doc.model_dump.return_value = current_state
        mock_doc.version = 3

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=_find_one_for_live_doc(create_log),
            ),
            patch(
                "app.audit.queries.AuditQueryService._resolve_model_class",
                return_value=MagicMock(
                    get=AsyncMock(return_value=mock_doc),
                ),
            ),
            patch.object(
                AuditLog,
                "find",
                return_value=MagicMock(
                    sort=MagicMock(
                        return_value=MagicMock(
                            to_list=AsyncMock(
                                return_value=[update_v3, update_v2],
                            ),
                        )
                    )
                ),
            ),
        ):
            result = await AuditQueryService.reconstruct_document_at_version(
                document_id=doc_id,
                target_version=1,
            )

            assert result["state"]["status"] == "extracted"
            assert result["state"]["verified"] is False
            assert result["version"] == 1
            assert result["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_reconstruct_intermediate_version(self):
        """Walking back to version 2 reverses only version 3 changes."""
        doc_id = PydanticObjectId()
        current_state = {
            "id": doc_id,
            "status": "modified",
            "verified": True,
            "version": 3,
        }

        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        update_v3 = _make_audit_log(
            doc_id,
            3,
            OperationType.UPDATE,
            changes=[_make_json_patch_change("verified", False)],
        )

        mock_doc = MagicMock()
        mock_doc.model_dump.return_value = current_state
        mock_doc.version = 3

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=_find_one_for_live_doc(create_log),
            ),
            patch(
                "app.audit.queries.AuditQueryService._resolve_model_class",
                return_value=MagicMock(
                    get=AsyncMock(return_value=mock_doc),
                ),
            ),
            patch.object(
                AuditLog,
                "find",
                return_value=MagicMock(
                    sort=MagicMock(
                        return_value=MagicMock(
                            to_list=AsyncMock(return_value=[update_v3]),
                        )
                    )
                ),
            ),
        ):
            result = await AuditQueryService.reconstruct_document_at_version(
                document_id=doc_id,
                target_version=2,
            )

            # status stayed "modified" (only v3 reversed, which changed verified)
            assert result["state"]["status"] == "modified"
            assert result["state"]["verified"] is False
            assert result["version"] == 2
            assert result["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_invalid_version_zero_raises(self):
        """Version 0 is invalid and raises ValueError."""
        doc_id = PydanticObjectId()
        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        mock_doc = MagicMock()
        mock_doc.model_dump.return_value = {"id": doc_id, "version": 3}
        mock_doc.version = 3

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=_find_one_for_live_doc(create_log),
            ),
            patch(
                "app.audit.queries.AuditQueryService._resolve_model_class",
                return_value=MagicMock(
                    get=AsyncMock(return_value=mock_doc),
                ),
            ),
        ):
            with pytest.raises(ValueError, match="must be between 1"):
                await AuditQueryService.reconstruct_document_at_version(
                    document_id=doc_id,
                    target_version=0,
                )

    @pytest.mark.asyncio
    async def test_invalid_version_too_high_raises(self):
        """Version higher than current raises ValueError."""
        doc_id = PydanticObjectId()
        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        mock_doc = MagicMock()
        mock_doc.model_dump.return_value = {"id": doc_id, "version": 3}
        mock_doc.version = 3

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=_find_one_for_live_doc(create_log),
            ),
            patch(
                "app.audit.queries.AuditQueryService._resolve_model_class",
                return_value=MagicMock(
                    get=AsyncMock(return_value=mock_doc),
                ),
            ),
        ):
            with pytest.raises(ValueError, match="must be between 1"):
                await AuditQueryService.reconstruct_document_at_version(
                    document_id=doc_id,
                    target_version=5,
                )

    @pytest.mark.asyncio
    async def test_no_audit_history_raises(self):
        """Document with no audit history raises ValueError."""
        doc_id = PydanticObjectId()

        with patch.object(
            AuditLog,
            "find_one",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(ValueError, match="No audit history"):
                await AuditQueryService.reconstruct_document_at_version(
                    document_id=doc_id,
                    target_version=1,
                )


# ---------------------------------------------------------------------------
# Tests: reconstruct_document_at_version (deleted documents)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReconstructDeletedDocument:
    """Tests for reconstructing versions of deleted documents via snapshot."""

    @pytest.mark.asyncio
    async def test_deleted_doc_uses_snapshot_as_starting_state(self):
        """For deleted docs, the DELETE log's snapshot is the starting state."""
        doc_id = PydanticObjectId()
        snapshot_state = {
            "id": str(doc_id),
            "status": "modified",
            "verified": True,
            "version": 3,
        }

        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        delete_log = _make_audit_log(
            doc_id,
            3,
            OperationType.DELETE,
            snapshot=snapshot_state,
            document_type="Source",
        )

        # find_one for CREATE returns create_log, for DELETE returns delete_log
        async def find_one_side_effect(query, *args, **kwargs):
            op = query.get("operation")
            if op == OperationType.DELETE:
                return delete_log
            return create_log

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=find_one_side_effect,
            ),
            patch.object(
                AuditLog,
                "find",
                return_value=MagicMock(
                    sort=MagicMock(
                        return_value=MagicMock(
                            to_list=AsyncMock(return_value=[]),
                        )
                    )
                ),
            ),
        ):
            result = await AuditQueryService.reconstruct_document_at_version(
                document_id=doc_id,
                target_version=3,
            )

            assert result["is_deleted"] is True
            assert result["state"]["status"] == "modified"
            assert result["state"]["verified"] is True

    @pytest.mark.asyncio
    async def test_deleted_doc_walk_back_to_version_1(self):
        """Deleted doc can be walked back to version 1 from snapshot."""
        doc_id = PydanticObjectId()
        snapshot_state = {
            "id": str(doc_id),
            "status": "modified",
            "verified": True,
            "version": 3,
        }

        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        delete_log = _make_audit_log(
            doc_id,
            3,
            OperationType.DELETE,
            snapshot=snapshot_state,
            document_type="Source",
        )

        update_v2 = _make_audit_log(
            doc_id,
            2,
            OperationType.UPDATE,
            changes=[_make_json_patch_change("status", "extracted")],
        )
        update_v3 = _make_audit_log(
            doc_id,
            3,
            OperationType.UPDATE,
            changes=[_make_json_patch_change("verified", False)],
        )

        async def find_one_side_effect(query, *args, **kwargs):
            op = query.get("operation")
            if op == OperationType.DELETE:
                return delete_log
            return create_log

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=find_one_side_effect,
            ),
            patch.object(
                AuditLog,
                "find",
                return_value=MagicMock(
                    sort=MagicMock(
                        return_value=MagicMock(
                            to_list=AsyncMock(
                                return_value=[update_v3, update_v2],
                            ),
                        )
                    )
                ),
            ),
        ):
            result = await AuditQueryService.reconstruct_document_at_version(
                document_id=doc_id,
                target_version=1,
            )

            assert result["is_deleted"] is True
            assert result["state"]["status"] == "extracted"
            assert result["state"]["verified"] is False
            assert result["version"] == 1

    @pytest.mark.asyncio
    async def test_deleted_doc_without_snapshot_raises(self):
        """Deleted doc without snapshot in DELETE log raises ValueError."""
        doc_id = PydanticObjectId()

        create_log = _make_audit_log(doc_id, 1, OperationType.CREATE)

        delete_log = _make_audit_log(
            doc_id,
            3,
            OperationType.DELETE,
            snapshot=None,  # no snapshot (old-style DELETE log)
            document_type="Source",
        )

        async def find_one_side_effect(query, *args, **kwargs):
            op = query.get("operation")
            if op == OperationType.DELETE:
                return delete_log
            return create_log

        with (
            patch.object(
                AuditLog,
                "find_one",
                new_callable=AsyncMock,
                side_effect=find_one_side_effect,
            ),
            patch(
                "app.audit.queries.AuditQueryService._resolve_model_class",
                return_value=MagicMock(
                    get=AsyncMock(return_value=None),
                ),
            ),
        ):
            with pytest.raises(ValueError, match="[Cc]annot reconstruct"):
                await AuditQueryService.reconstruct_document_at_version(
                    document_id=doc_id,
                    target_version=1,
                )


# ---------------------------------------------------------------------------
# Tests: TextDiffStrategy.reverse_text_patches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReverseTextPatches:
    """Tests for TextDiffStrategy.reverse_text_patches."""

    def test_reverse_patches_recovers_original(self):
        """Reversing patches and applying to modified text yields original."""
        strategy = TextDiffStrategy()

        original = "The quick brown fox jumps over the lazy dog. " * 50
        modified = "The slow brown cat jumps over the lazy dog. " * 50

        forward = strategy.compute_changes(original, modified, "text")
        reversed_patch = strategy.reverse_text_patches(forward["patch_text"])

        # Apply reversed patch to the modified text
        recovered = strategy.reconstruct_text(modified, reversed_patch)

        assert recovered == original

    def test_reverse_patches_with_insertions(self):
        """Reverse handles text where content was inserted."""
        strategy = TextDiffStrategy()

        original = "AAAA" * 500
        modified = "AAAA" * 250 + "BBBB" * 100 + "AAAA" * 250

        forward = strategy.compute_changes(original, modified, "text")
        reversed_patch = strategy.reverse_text_patches(forward["patch_text"])

        recovered = strategy.reconstruct_text(modified, reversed_patch)

        assert recovered == original

    def test_reverse_patches_with_deletions(self):
        """Reverse handles text where content was removed."""
        strategy = TextDiffStrategy()

        original = "AAAA" * 250 + "BBBB" * 100 + "AAAA" * 250
        modified = "AAAA" * 500

        forward = strategy.compute_changes(original, modified, "text")
        reversed_patch = strategy.reverse_text_patches(forward["patch_text"])

        recovered = strategy.reconstruct_text(modified, reversed_patch)

        assert recovered == original

    def test_reverse_patches_idempotent_round_trip(self):
        """Reversing twice yields the original forward patch behavior."""
        strategy = TextDiffStrategy()

        original = "Hello World! " * 200
        modified = "Hello Universe! " * 200

        forward = strategy.compute_changes(original, modified, "text")
        reversed_once = strategy.reverse_text_patches(forward["patch_text"])
        reversed_twice = strategy.reverse_text_patches(reversed_once)

        # Applying double-reversed patch to original should give modified
        result = strategy.reconstruct_text(original, reversed_twice)

        assert result == modified


# ---------------------------------------------------------------------------
# Tests: JsonPatchStrategy stores old_value
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJsonPatchStoresOldValue:
    """Tests that JsonPatchStrategy.compute_changes includes old_value."""

    def test_old_value_stored_for_string(self):
        from app.audit.strategies import JsonPatchStrategy

        strategy = JsonPatchStrategy()
        changes = strategy.compute_changes("old_status", "new_status", "status")

        assert "old_value" in changes
        assert changes["old_value"] == "old_status"

    def test_old_value_stored_for_number(self):
        from app.audit.strategies import JsonPatchStrategy

        strategy = JsonPatchStrategy()
        changes = strategy.compute_changes(42, 99, "count")

        assert changes["old_value"] == 42

    def test_old_value_stored_for_dict(self):
        from app.audit.strategies import JsonPatchStrategy

        strategy = JsonPatchStrategy()
        old_dict = {"articleType": "Single Incident", "confidence": 0.9}
        new_dict = {"articleType": "Multiple Incidents", "confidence": 0.8}
        changes = strategy.compute_changes(old_dict, new_dict, "article_scope")

        assert changes["old_value"] == old_dict

    def test_old_value_stored_for_none(self):
        from app.audit.strategies import JsonPatchStrategy

        strategy = JsonPatchStrategy()
        changes = strategy.compute_changes(None, "new_value", "field")

        assert changes["old_value"] is None

    def test_old_value_stored_for_bool(self):
        from app.audit.strategies import JsonPatchStrategy

        strategy = JsonPatchStrategy()
        changes = strategy.compute_changes(False, True, "verified")

        assert changes["old_value"] is False

    def test_old_value_stored_for_list(self):
        from app.audit.strategies import JsonPatchStrategy

        strategy = JsonPatchStrategy()
        changes = strategy.compute_changes(["a", "b"], ["a", "b", "c"], "tags")

        assert changes["old_value"] == ["a", "b"]


# ---------------------------------------------------------------------------
# Tests: AuditLog snapshot field
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuditLogSnapshot:
    """Tests that AuditLog model supports the snapshot field."""

    def test_snapshot_defaults_to_none(self):
        """Snapshot field is None by default."""
        log = AuditLog.model_construct(
            document_id=PydanticObjectId(),
            document_type="Source",
            version=1,
            operation=OperationType.CREATE,
            snapshot=None,
        )
        assert log.snapshot is None

    def test_snapshot_stores_dict(self):
        """Snapshot field can store a full document dict."""
        snapshot = {"status": "extracted", "verified": False, "version": 2}
        log = AuditLog.model_construct(
            document_id=PydanticObjectId(),
            document_type="Source",
            version=2,
            operation=OperationType.DELETE,
            snapshot=snapshot,
        )
        assert log.snapshot == snapshot
        assert log.snapshot["status"] == "extracted"
