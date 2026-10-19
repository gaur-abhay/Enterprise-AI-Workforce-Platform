"""Wire models for confirmations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ai_employee.db.models import Approval, ApprovalStatus


class DecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ApprovalView(BaseModel):
    approval_id: uuid.UUID
    task_id: uuid.UUID
    tool_name: str
    # Exactly what will run if approved.
    arguments: dict[str, Any]
    status: ApprovalStatus
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def of(cls, approval: Approval) -> ApprovalView:
        return cls(
            approval_id=approval.id,
            task_id=approval.task_id,
            tool_name=approval.tool_name,
            arguments=approval.arguments,
            status=approval.status,
            created_at=approval.created_at,
            decided_at=approval.decided_at,
        )
