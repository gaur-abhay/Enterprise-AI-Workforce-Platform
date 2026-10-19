"""The turn queue: a Postgres table claimed with FOR UPDATE SKIP LOCKED.

Enqueue and read run in tenant sessions. Claim, lease renewal and completion are queue
infrastructure that spans tenants, so they run in admin sessions and touch only queue state.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import and_, func, or_, select, update

from ai_employee.context import SYSTEM_ACTOR, TurnContext
from ai_employee.db import admin_session, tenant_session
from ai_employee.db.models import TaskStatus, TurnTask

MAX_ATTEMPTS = 3


def enqueue(ctx: TurnContext, message: str) -> uuid.UUID:
    task = TurnTask(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        employee_id=ctx.employee_id,
        actor=str(ctx.actor),
        trigger=ctx.trigger,
        correlation_id=ctx.correlation_id,
        actor_principals=list(ctx.actor_principals),
        conversation_ref=dict(ctx.conversation_ref) if ctx.conversation_ref else None,
        message=message,
    )
    with tenant_session(ctx.tenant_id) as session:
        session.add(task)
    return task.id


def get(tenant_id: uuid.UUID, task_id: uuid.UUID) -> TurnTask | None:
    """RLS makes another tenant's task indistinguishable from a missing one."""
    with tenant_session(tenant_id) as session:
        return session.get(TurnTask, task_id)


def context_for(task: TurnTask) -> TurnContext:
    actor: uuid.UUID | Literal["system"] = (
        "system" if task.actor == SYSTEM_ACTOR else uuid.UUID(task.actor)
    )
    return TurnContext(
        tenant_id=task.tenant_id,
        employee_id=task.employee_id,
        actor=actor,
        trigger=task.trigger,  # type: ignore[arg-type]
        correlation_id=task.correlation_id,
        actor_principals=tuple(task.actor_principals),
        conversation_ref=task.conversation_ref,
    )


def claim_next(worker_id: str, lease: timedelta) -> TurnTask | None:
    """Take the oldest queued task, or a running one whose worker stopped renewing its lease."""
    claimable = or_(
        TurnTask.status == TaskStatus.QUEUED,
        and_(TurnTask.status == TaskStatus.RUNNING, TurnTask.lease_expires_at < func.now()),
    )
    next_id = (
        select(TurnTask.id)
        .where(claimable)
        .order_by(TurnTask.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    with admin_session() as session:
        return session.scalars(
            update(TurnTask)
            .where(TurnTask.id == next_id)
            .values(
                status=TaskStatus.RUNNING,
                attempts=TurnTask.attempts + 1,
                claimed_by=worker_id,
                lease_expires_at=func.now() + lease,
                started_at=func.coalesce(TurnTask.started_at, func.now()),
            )
            .returning(TurnTask)
        ).one_or_none()


def _owned(task_id: uuid.UUID, worker_id: str) -> Any:
    # A worker that lost its lease must not overwrite the task's new owner.
    return and_(
        TurnTask.id == task_id,
        TurnTask.claimed_by == worker_id,
        TurnTask.status == TaskStatus.RUNNING,
    )


def renew(task_id: uuid.UUID, worker_id: str, lease: timedelta) -> bool:
    with admin_session() as session:
        result = session.execute(
            update(TurnTask)
            .where(_owned(task_id, worker_id))
            .values(lease_expires_at=func.now() + lease)
        )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def complete(task_id: uuid.UUID, worker_id: str, result: dict[str, Any]) -> None:
    with admin_session() as session:
        session.execute(
            update(TurnTask)
            .where(_owned(task_id, worker_id))
            .values(
                status=TaskStatus.SUCCEEDED,
                result=result,
                error=None,
                lease_expires_at=None,
                finished_at=func.now(),
            )
        )


def fail(task_id: uuid.UUID, worker_id: str, error: str, *, retry: bool) -> None:
    """Record a failure; requeue for another attempt or mark it terminal."""
    terminal = {"status": TaskStatus.FAILED, "finished_at": func.now()}
    with admin_session() as session:
        session.execute(
            update(TurnTask)
            .where(_owned(task_id, worker_id))
            .values(
                error=error,
                lease_expires_at=None,
                claimed_by=None,
                **({"status": TaskStatus.QUEUED} if retry else terminal),
            )
        )
