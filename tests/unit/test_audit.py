"""
Unit tests for the audit system.

Tests audit context management, audit strategies, and audit trail creation.
"""

import pytest

from app.audit.context import AuditContext
from app.audit.strategies import (
    JsonPatchStrategy,
    TextDiffStrategy,
    ReferenceTrackingStrategy,
)
from app.audit.enums import ChangeType, OperationType
from app.models.sources import Source
from app.audit.models import AuditLog


@pytest.mark.unit
class TestAuditContext:
    """Tests for AuditContext context management."""

    def test_set_and_get_user(self):
        """Test setting and getting user in audit context."""
        user_id = "test-user-123"
        AuditContext.set_user(user_id)
        assert AuditContext.get_user() == user_id

    def test_get_user_default_none(self):
        """Test that default user is None."""
        AuditContext.set_user(None)
        assert AuditContext.get_user() is None

    def test_with_user_context_manager(self):
        """Test the with_user context manager."""
        user_id = "context-user-456"

        # Verify no user set initially
        AuditContext.set_user(None)
        assert AuditContext.get_user() is None

        # Use context manager
        with AuditContext.with_user(user_id):
            assert AuditContext.get_user() == user_id

        # Verify user is cleared after context
        assert AuditContext.get_user() is None

    def test_with_user_nested_contexts(self):
        """Test nested audit contexts."""
        user1 = "user-1"
        user2 = "user-2"

        with AuditContext.with_user(user1):
            assert AuditContext.get_user() == user1

            with AuditContext.with_user(user2):
                assert AuditContext.get_user() == user2

            # Should revert to user1 after inner context
            assert AuditContext.get_user() == user1

        # Should be None after all contexts
        assert AuditContext.get_user() is None


@pytest.mark.unit
class TestJsonPatchStrategy:
    """Tests for JsonPatchStrategy."""

    def test_should_handle_small_strings(self):
        """Test that strategy handles small strings."""
        strategy = JsonPatchStrategy()
        old_val = "short string"
        new_val = "another short string"

        assert strategy.should_handle(old_val, new_val, "field_name") is True

    def test_should_not_handle_large_strings(self):
        """Test that strategy doesn't handle strings > 1024 chars."""
        strategy = JsonPatchStrategy()
        old_val = "x" * 2000
        new_val = "y" * 2000

        assert strategy.should_handle(old_val, new_val, "field_name") is False

    def test_should_handle_non_strings(self):
        """Test that strategy handles non-string values."""
        strategy = JsonPatchStrategy()

        # Numbers
        assert strategy.should_handle(42, 43, "number_field") is True

        # Lists
        assert strategy.should_handle([1, 2], [1, 2, 3], "list_field") is True

        # Dicts
        assert strategy.should_handle({"a": 1}, {"a": 2}, "dict_field") is True

    def test_compute_changes_simple_value(self):
        """Test computing changes for simple value change."""
        strategy = JsonPatchStrategy()
        changes = strategy.compute_changes("old", "new", "test_field")

        assert changes["change_type"] == ChangeType.JSON_PATCH
        assert changes["field_path"] == "test_field"
        assert "patches" in changes
        assert changes["old_value_size"] == 3  # len("old")
        assert changes["new_value_size"] == 3  # len("new")

    def test_compute_changes_dict_value(self):
        """Test computing changes for dict value."""
        strategy = JsonPatchStrategy()
        old_dict = {"key1": "value1"}
        new_dict = {"key1": "value2"}

        changes = strategy.compute_changes(old_dict, new_dict, "nested.dict")

        assert changes["change_type"] == ChangeType.JSON_PATCH
        assert changes["field_path"] == "nested.dict"
        assert "patches" in changes


@pytest.mark.unit
class TestTextDiffStrategy:
    """Tests for TextDiffStrategy."""

    def test_should_handle_large_strings(self):
        """Test that strategy handles strings > 1024 chars."""
        strategy = TextDiffStrategy()
        old_val = "x" * 2000
        new_val = "y" * 2000

        assert strategy.should_handle(old_val, new_val, "large_text") is True

    def test_should_not_handle_small_strings(self):
        """Test that strategy doesn't handle small strings."""
        strategy = TextDiffStrategy()
        old_val = "short"
        new_val = "text"

        assert strategy.should_handle(old_val, new_val, "small_text") is False

    def test_should_not_handle_non_strings(self):
        """Test that strategy only handles strings."""
        strategy = TextDiffStrategy()

        assert strategy.should_handle(42, 43, "number") is False
        assert strategy.should_handle([1, 2], [1, 3], "list") is False

    def test_compute_changes_large_text(self):
        """Test computing text diff patches."""
        strategy = TextDiffStrategy()
        old_text = "a" * 2000
        new_text = "a" * 1900 + "b" * 100

        changes = strategy.compute_changes(old_text, new_text, "article_text")

        assert changes["change_type"] == ChangeType.TEXT_DIFF
        assert changes["field_path"] == "article_text"
        assert "patch_text" in changes
        assert changes["old_size"] == 2000
        assert changes["new_size"] == 2000
        assert "compression_ratio" in changes

    def test_reconstruct_text(self):
        """Test text reconstruction from patches."""
        strategy = TextDiffStrategy()
        original = "Hello World! " * 200  # Make it large enough
        modified = "Hello Universe! " * 200

        # Compute diff
        changes = strategy.compute_changes(original, modified, "test")
        patch_text = changes["patch_text"]

        # Reconstruct
        reconstructed = strategy.reconstruct_text(original, patch_text)

        assert reconstructed == modified


@pytest.mark.unit
class TestReferenceTrackingStrategy:
    """Tests for ReferenceTrackingStrategy."""

    def test_should_handle_configured_reference_fields(self):
        """Test that strategy handles configured reference fields."""
        config = {"IncidentReport": ["sources", "primary_source"]}
        strategy = ReferenceTrackingStrategy(config)

        assert strategy.should_handle([], [], "sources", "IncidentReport") is True
        assert (
            strategy.should_handle([], [], "primary_source", "IncidentReport") is True
        )

    def test_should_not_handle_unconfigured_fields(self):
        """Test that strategy doesn't handle unconfigured fields."""
        config = {"IncidentReport": ["sources"]}
        strategy = ReferenceTrackingStrategy(config)

        assert strategy.should_handle([], [], "other_field", "IncidentReport") is False

    def test_should_not_handle_without_document_type(self):
        """Test that strategy requires document_type."""
        config = {"IncidentReport": ["sources"]}
        strategy = ReferenceTrackingStrategy(config)

        assert strategy.should_handle([], [], "sources", None) is False

    def test_compute_changes_list_of_dicts(self):
        """Test computing changes for list of dict references."""
        config = {"IncidentReport": ["sources"]}
        strategy = ReferenceTrackingStrategy(config)

        old_value = [{"id": "source1"}, {"id": "source2"}]
        new_value = [{"id": "source2"}, {"id": "source3"}]

        changes = strategy.compute_changes(
            old_value, new_value, "sources", "IncidentReport"
        )

        assert changes["change_type"] == ChangeType.REFERENCE_CHANGE
        assert changes["field_path"] == "sources"
        assert "source1" in changes["removed_references"]
        assert "source3" in changes["added_references"]
        assert changes["reference_count_change"] == 0  # 2 -> 2

    def test_extract_ids_from_none(self):
        """Test extracting IDs from None value."""
        config = {}
        strategy = ReferenceTrackingStrategy(config)

        ids = strategy._extract_ids(None)
        assert ids == []

    def test_extract_ids_from_dict_with_id(self):
        """Test extracting ID from dict."""
        config = {}
        strategy = ReferenceTrackingStrategy(config)

        ids = strategy._extract_ids({"id": "test-id-123"})
        assert ids == ["test-id-123"]

    def test_extract_ids_from_list_of_dicts(self):
        """Test extracting IDs from list of dicts."""
        config = {}
        strategy = ReferenceTrackingStrategy(config)

        value = [{"id": "id1"}, {"id": "id2"}, {"_id": "id3"}]
        ids = strategy._extract_ids(value)

        assert "id1" in ids
        assert "id2" in ids
        assert "id3" in ids


@pytest.mark.integration
class TestAuditIntegration:
    """Integration tests for audit system with database."""

    @pytest.mark.asyncio
    async def test_source_creation_audit(self, test_db):
        """Test that source creation is audited."""
        user_id = "test-user-creation"

        with AuditContext.with_user(user_id):
            source = Source(
                article_text="Test article for audit",
                url="https://example.com/audit-test",
                source_type="news",
            )
            await source.insert()

        # Verify audit fields were set
        assert source.created_by == user_id
        assert source.updated_by == user_id
        assert source.version == 1

        # Verify audit log was created
        audit_logs = await AuditLog.find(AuditLog.document_id == source.id).to_list()
        assert len(audit_logs) > 0
        assert audit_logs[0].operation == OperationType.CREATE

    @pytest.mark.asyncio
    async def test_source_update_audit(self, test_db, sample_source):
        """Test that source updates are audited."""
        user_id = "test-user-update"

        # Update the source
        with AuditContext.with_user(user_id):
            sample_source.status = "modified"
            await sample_source.save()

        # Verify audit fields were updated
        assert sample_source.updated_by == user_id
        assert sample_source.version == 2

        # Verify audit log was created for update
        audit_logs = await AuditLog.find(
            AuditLog.document_id == sample_source.id,
            AuditLog.operation == OperationType.UPDATE,
        ).to_list()
        assert len(audit_logs) > 0

    @pytest.mark.asyncio
    async def test_incident_update_audit(self, test_db, sample_incident):
        """Test that incident updates are audited."""
        user_id = "test-user-incident"

        # Update the incident
        with AuditContext.with_user(user_id):
            sample_incident.verified = True
            await sample_incident.save()

        # Verify audit fields
        assert sample_incident.updated_by == user_id
        assert sample_incident.version >= 2

        # Verify audit log
        audit_logs = await AuditLog.find(
            AuditLog.document_id == sample_incident.id,
            AuditLog.operation == OperationType.UPDATE,
        ).to_list()
        assert len(audit_logs) > 0

    @pytest.mark.asyncio
    async def test_audit_without_user_context(self, test_db):
        """Test that audit works even without explicit user context."""
        source = Source(
            article_text="Test without user",
            url="https://example.com/no-user",
        )
        await source.insert()

        # created_by should be None
        assert source.created_by is None
        assert source.version == 1

    @pytest.mark.asyncio
    async def test_audit_log_retrieval(self, test_db, sample_source):
        """Test retrieving audit logs for a document."""
        user_id = "test-audit-retrieval"

        # Make multiple updates
        with AuditContext.with_user(user_id):
            sample_source.status = "modified"
            await sample_source.save()

            sample_source.article_title = "Updated Title"
            await sample_source.save()

        # Retrieve all audit logs for this source
        audit_logs = (
            await AuditLog.find(AuditLog.document_id == sample_source.id)
            .sort("+timestamp")
            .to_list()
        )

        # Should have CREATE + 2 UPDATEs
        assert len(audit_logs) >= 3
        assert audit_logs[0].operation == OperationType.CREATE
        assert any(log.operation == OperationType.UPDATE for log in audit_logs)
