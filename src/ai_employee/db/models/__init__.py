"""ORM models. Importing this package registers every table on Base.metadata."""

from ai_employee.db.models.base import Base
from ai_employee.db.models.execution import SideEffectClass, ToolCall, ToolOutcome
from ai_employee.db.models.knowledge import Chunk, Document
from ai_employee.db.models.tenancy import (
    Employee,
    SourceConnection,
    SourceKind,
    Tenant,
    TenantStatus,
    User,
    UserRole,
)

__all__ = [
    "Base",
    "Chunk",
    "Document",
    "Employee",
    "SideEffectClass",
    "SourceConnection",
    "SourceKind",
    "Tenant",
    "TenantStatus",
    "ToolCall",
    "ToolOutcome",
    "User",
    "UserRole",
]
