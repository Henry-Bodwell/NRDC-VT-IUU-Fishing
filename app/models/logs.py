from datetime import datetime, timezone
from beanie import (
    Document,
    Insert,
    PydanticObjectId,
    Replace,
    SaveChanges,
    Delete,
    before_event,
    after_event,
)
from pydantic import BaseModel, Field


class LogContext(BaseModel):
    user_id: str | None = Field(default=None)
    action: str | None = Field(
        default=None, description="Name of action, e.g. new_report, edit_report"
    )
    source: str | None = Field(default=None)


class Log(Document):
    document_id: PydanticObjectId
    collection_name: str
    operation: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    changes: dict[str, dict[str, any]] | None = Field(default=None)
    before_state: dict[str, any] | None = Field(default=None)
    after_state: dict[str, any] | None = Field(default=None)

    context: LogContext | None = Field(default=None)

    class Settings:
        name = "logs"
        indexes = ["document_id", "collection_name", "timestamp", "context.user_id"]


class LogMixin:
    """Mixing to add loigging to any given model"""

    _log_context: LogContext | None = Field(default=None)
    _original_state: dict[str, any] = Field(default=None)

    def set_log_context(self, context: LogContext) -> None:
        """Set the log context for this operation"""
        self._log_context = context
        return self

    @before_event(Replace, SaveChanges)
    async def _capture_before_state(self):
        """Capture state prior to changes"""
        if hasattr(self, "id") and self.id:
            current_doc = await self.__class__.get(self.id)
            if current_doc:
                self._original_state = current_doc.model_dump(
                    exclude={"_log_context", "_original_state"}
                )

    @after_event(Insert)
    async def _log_insert(self):
        """Log an insert operation"""
        log_entry = Log(
            document_id=PydanticObjectId(self.id),
            collection_name=self.__class__.Settings.name,
            operation="insert",
            before_state=None,
            after_state=self.model_dump(exclude={"_log_context", "_original_state"}),
            context=self._log_context,
        )
        await log_entry.insert()

    @after_event(Replace, SaveChanges)
    async def _log_update(self):
        """Log update operations"""

        current_state = self.model_dump(exclude={"_log_context", "_original_state"})
        changes = {}

        if self._original_state:
            for field, new_value in current_state.items():
                old_value = self._original_state.get(field)
                if old_value != new_value:
                    changes[field] = {"old_value": old_value, "new_value": new_value}

        if changes or not self._original_state:
            log_entry = Log(
                document_id=PydanticObjectId(self.id),
                collection_name=self.__class__.Settings.name,
                operation="update",
                changes=changes if changes else None,
                before_state=self._original_state,
                after_state=current_state,
                context=self._log_context,
            )
            await log_entry.insert()

    @before_event(Delete)
    async def _capture_before_delete(self):
        self._original_state = self.model_dump(
            exclude={"_log_context", "_original_state"}
        )

    @after_event(Delete)
    async def _log_delete(self):
        """log delete operation"""
        log_entry = Log(
            document_id=PydanticObjectId(self.id),
            collection_name=self.__class__.Settings.name,
            operation="delete",
            before_state=self._original_state,
            context=self._log_context,
        )

        await log_entry.insert()
