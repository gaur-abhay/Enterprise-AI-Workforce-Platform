"""Execution plane: the tool-call audit log."""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_employee.db.models.base import Base, CreatedAt, TenantScoped, UUIDPrimaryKey, str_enum


class SideEffectClass(enum.StrEnum):
    READ = "read"
    WRITE = "write"
    IRREVERSIBLE = "irreversible"


class ToolOutcome(enum.StrEnum):
    OK = "ok"
    ERROR = "error"
    PENDING_APPROVAL = "pending_approval"


class ToolCall(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    """One row per dispatched tool call, whatever its outcome. Append-only."""

    __tablename__ = "tool_calls"

    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column()
    # User id, or "system" for scheduled runs.
    actor: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(100))
    side_effect_class: Mapped[SideEffectClass | None] = mapped_column(
        str_enum(SideEffectClass, "side_effect_class")
    )
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome: Mapped[ToolOutcome] = mapped_column(str_enum(ToolOutcome, "tool_outcome"))
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
