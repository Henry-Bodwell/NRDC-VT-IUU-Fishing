from typing import Optional
import contextvars
from contextlib import contextmanager

# Context management for user tracking
audit_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "audit_user", default=None
)


class AuditContext:
    """Manages audit context throughout request lifecycle"""

    @classmethod
    def set_user(cls, user_id: str):
        audit_context.set(user_id)

    @classmethod
    def get_user(cls) -> Optional[str]:
        return audit_context.get()

    @classmethod
    @contextmanager
    def with_user(cls, user_id: str):
        token = audit_context.set(user_id)
        try:
            yield
        finally:
            audit_context.set(None)
