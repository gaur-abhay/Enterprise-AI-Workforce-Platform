"""Wire models for turns. Never the ORM classes."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from ai_employee.db.models import TaskStatus, TurnTask


class TurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class Source(BaseModel):
    chunk_id: str
    document_id: str
    source: str
    title: str
    uri: str
    page: int | None
    chunk_index: int
    indexed_at: str
    score: float
    content: str


class TurnResult(BaseModel):
    answer: str
    # Passages retrieved during the turn, not necessarily the ones cited.
    sources: list[Source]
    tool_calls: list[dict[str, Any]]


class TaskAccepted(BaseModel):
    task_id: uuid.UUID
    status: TaskStatus


class TaskView(BaseModel):
    task_id: uuid.UUID
    status: TaskStatus
    # Correlation id for this turn's logs and audit rows.
    request_id: str
    result: TurnResult | None = None
    # Deliberately generic; the stored error is for operators, not callers.
    error: str | None = None

    @classmethod
    def of(cls, task: TurnTask) -> TaskView:
        return cls(
            task_id=task.id,
            status=task.status,
            request_id=task.correlation_id,
            result=TurnResult.model_validate(task.result) if task.result else None,
            error="the turn failed" if task.status is TaskStatus.FAILED else None,
        )
