"""Approvals: a suspended turn's held calls, confirmed or declined by the requester.

The worker records requests when a turn suspends; the requester's decision requeues the task
once nothing it waits on is pending, and any worker then resumes it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from ai_employee.agent import ApprovalRequest
from ai_employee.context import TurnContext
from ai_employee.db import tenant_session
from ai_employee.db.models import Approval, ApprovalStatus, TaskStatus, TurnTask
from ai_employee.tools import Decision, PendingApproval, dispatcher, registry


class ApprovalError(RuntimeError):
    pass


class ApprovalNotFoundError(ApprovalError):
    pass


class NotApproverError(ApprovalError):
    pass


class AlreadyDecidedError(ApprovalError):
    pass


def record(task: TurnTask, ctx: TurnContext, requests: Sequence[ApprovalRequest]) -> None:
    """Store the held calls. Idempotent: a re-recorded suspension adds nothing."""
    rows = [
        {
            "id": uuid.uuid4(),
            "tenant_id": task.tenant_id,
            "task_id": task.id,
            "tool_call_id": r.tool_call_id,
            "tool_name": r.tool_name,
            "side_effect_class": registry.get(r.tool_name).side_effect_class,  # type: ignore[union-attr]
            "arguments": r.arguments,
            "approver": task.actor,
        }
        for r in requests
    ]
    with tenant_session(task.tenant_id) as session:
        added = session.scalars(
            insert(Approval)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["task_id", "tool_call_id"])
            .returning(Approval.tool_call_id)
        ).all()
    for r in requests:
        if r.tool_call_id in added:
            dispatcher.audit(
                ctx, r.tool_name, r.arguments, PendingApproval(r.tool_name, r.arguments)
            )


def decisions_for(task: TurnTask) -> dict[str, Decision] | None:
    """The decisions to resume with, or None when the task holds no decided approvals."""
    with tenant_session(task.tenant_id) as session:
        rows = session.scalars(select(Approval).where(Approval.task_id == task.id)).all()
    decided = [a for a in rows if a.status is not ApprovalStatus.PENDING]
    if not decided or len(decided) != len(rows):
        return None
    return {
        a.tool_call_id: Decision(approved=a.status is ApprovalStatus.APPROVED, reason=a.reason)
        for a in decided
    }


def pending_for(tenant_id: uuid.UUID, approver: uuid.UUID) -> list[Approval]:
    with tenant_session(tenant_id) as session:
        return list(
            session.scalars(
                select(Approval)
                .where(
                    Approval.approver == str(approver), Approval.status == ApprovalStatus.PENDING
                )
                .order_by(Approval.created_at)
            )
        )


def for_task(tenant_id: uuid.UUID, task_id: uuid.UUID) -> list[Approval]:
    with tenant_session(tenant_id) as session:
        return list(session.scalars(select(Approval).where(Approval.task_id == task_id)))


def decide(
    tenant_id: uuid.UUID,
    approval_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    approved: bool,
    reason: str | None = None,
) -> Approval:
    """Apply the requester's decision; requeue the turn when nothing else is pending."""
    with tenant_session(tenant_id) as session:
        approval = session.get(Approval, approval_id)
        if approval is None:
            raise ApprovalNotFoundError("no such approval")
        # Serialises decisions on one task, so exactly one of them requeues it.
        session.execute(
            select(TurnTask.id).where(TurnTask.id == approval.task_id).with_for_update()
        )
        session.refresh(approval)
        if approval.approver != str(user_id):
            raise NotApproverError("only the person the coworker is acting for can confirm this")
        if approval.status is not ApprovalStatus.PENDING:
            raise AlreadyDecidedError(f"already {approval.status.value}")

        approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        approval.reason = reason
        approval.decided_at = func.now()
        session.flush()

        still_pending = session.scalar(
            select(func.count())
            .select_from(Approval)
            .where(Approval.task_id == approval.task_id, Approval.status == ApprovalStatus.PENDING)
        )
        if not still_pending:
            # Attempts count failures within one run, not the pauses between runs.
            session.execute(
                update(TurnTask)
                .where(
                    TurnTask.id == approval.task_id,
                    TurnTask.status == TaskStatus.AWAITING_APPROVAL,
                )
                .values(status=TaskStatus.QUEUED, attempts=0)
            )
        session.refresh(approval)
        return approval
