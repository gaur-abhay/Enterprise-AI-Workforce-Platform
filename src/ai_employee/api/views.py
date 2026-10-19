"""Shared template rendering for the admin and chat pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from ai_employee.api.identity import Identity
from ai_employee.db.models import ApprovalStatus, TaskStatus, TurnTask
from ai_employee.execution import approvals

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

FINISHED = (TaskStatus.SUCCEEDED, TaskStatus.FAILED)


def reply_context(identity: Identity, task: TurnTask) -> dict[str, Any]:
    pending = []
    if task.status is TaskStatus.AWAITING_APPROVAL:
        pending = [
            a
            for a in approvals.for_task(identity.tenant_id, task.id)
            if a.status is ApprovalStatus.PENDING
        ]
    return {
        "task": task,
        "finished": FINISHED,
        "pending": pending,
        # Only the requester can confirm; anyone else sees what the coworker is waiting on.
        "can_decide": str(identity.user_id) == task.actor,
    }
