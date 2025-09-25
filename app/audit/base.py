from datetime import datetime, timezone
import logging
from typing import Optional, Dict, Any
from beanie import Delete, Document, Insert, Replace, Update, before_event, after_event
from pydantic import Field
from .context import AuditContext

logger = logging.getLogger(__name__)


class AuditedDocument(Document):
    """Base class for all documents that need audit trails"""

    # Basic audit fields stored in main document
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: Optional[str] = None
    version: int = Field(default=1)

    # Internal state tracking
    _original_state: Optional[Dict[str, Any]] = None

    @before_event([Update, Replace])
    async def capture_original_state(self):
        """Capture current state before changes for comparison"""
        logger.info(
            f"before_event: Capturing original state for {self.__class__.__name__}"
        )
        if self.id:
            current_doc = await self.__class__.get(self.id)
            if current_doc:
                self._original_state = current_doc.model_dump(
                    exclude={"_original_state"}
                )
                logger.info(
                    f"Original state captured: {len(self._original_state)} fields"
                )
            else:
                logger.warning(f"Could not fetch current document for id {self.id}")

        else:
            logger.warning("Document has no ID; cannot capture original state")

    @before_event([Update, Replace])
    async def update_audit_fields(self):
        """Update audit fields before save"""
        self.updated_at = datetime.now(timezone.utc)
        self.updated_by = AuditContext.get_user()
        self.version += 1

    @before_event(Insert)
    async def set_creation_audit_fields(self):
        """Set creation audit fields"""
        current_user = AuditContext.get_user()
        now = datetime.now(timezone.utc)
        logger.info(f"Setting creation audit fields: user={current_user}, time={now}")
        if not self.created_at:
            self.created_at = now
        if not self.created_by:
            self.created_by = current_user
        if not self.updated_at:
            self.updated_at = now
        if not self.updated_by:
            self.updated_by = current_user

    @after_event(Insert)
    async def audit_create(self):
        """Log document creation"""
        # Import here to avoid circular imports
        from .service import AuditService

        try:
            await AuditService.log_create(self)
        except Exception as e:
            logger.warning(f"Audit logging failed for create: {e}")

    @after_event([Update, Replace])
    async def audit_update(self):
        """Log document updates"""
        # Import here to avoid circular imports
        from .service import AuditService

        logger.info(f"after_event: Auditing update for {self.__class__.__name__}")
        logger.info((f"Has original state: {self._original_state is not None}"))

        if self._original_state:
            try:
                entry = await AuditService.log_update(self, self._original_state)
                if entry:
                    logger.info(f"Audit log created with id {entry.id}")
                else:
                    logger.info("No changes detected; no audit log created")
            except Exception as e:
                logger.warning(f"Audit logging failed for update: {e}")

    @after_event(Delete)
    async def audit_delete(self):
        """Log document deletion"""
        # Import here to avoid circular imports
        from .service import AuditService

        try:
            await AuditService.log_delete(self)
        except Exception as e:
            logger.warning(f"Audit logging failed for delete: {e}")
