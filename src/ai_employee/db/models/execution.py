"""Execution plane: turn queue, approvals, outbox and the tool-call audit log."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class TaskStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    # Suspended on an interrupt; requeued once every approval it waits on is decided.
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TurnTask(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    """One queued agent turn. Its id is also the checkpointer thread id."""

    __tablename__ = "turn_tasks"
    __table_args__ = (
        # Serves the claim query: oldest claimable task first.
        Index("ix_turn_tasks_claimable", "status", "created_at"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column()
    actor: Mapped[str] = mapped_column(String(64))
    trigger: Mapped[str] = mapped_column(String(16))
    correlation_id: Mapped[str] = mapped_column(String(64))
    actor_principals: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    conversation_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    message: Mapped[str] = mapped_column(Text)

    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus, "task_status"), default=TaskStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(100))
    # A running task whose lease has passed is presumed abandoned and may be reclaimed.
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Approval(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    """A held tool call awaiting the requester's confirmation, for exactly these arguments."""

    __tablename__ = "approvals"
    __table_args__ = (
        # The worker may record the same suspension twice after a crash.
        UniqueConstraint("task_id", "tool_call_id"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("turn_tasks.id", ondelete="CASCADE"))
    # The model's id for the call; how the resumed graph matches a decision to its call.
    tool_call_id: Mapped[str] = mapped_column(String(100))
    tool_name: Mapped[str] = mapped_column(String(100))
    side_effect_class: Mapped[SideEffectClass] = mapped_column(
        str_enum(SideEffectClass, "side_effect_class")
    )
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Who must confirm: the actor the turn runs for.
    approver: Mapped[str] = mapped_column(String(64))
    status: Mapped[ApprovalStatus] = mapped_column(
        str_enum(ApprovalStatus, "approval_status"), default=ApprovalStatus.PENDING, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class OutboxMessage(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    """Email the coworker sent. Delivery is stubbed until a mail connection exists."""

    __tablename__ = "outbox_messages"

    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    sent_by: Mapped[str] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(64))
