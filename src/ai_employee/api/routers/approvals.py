"""Confirmations: the requester approves or declines what the coworker wants to do."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

from ai_employee.api.identity import Identity, current_identity
from ai_employee.api.schemas.approvals import ApprovalView, DecisionRequest
from ai_employee.api.views import reply_context, templates
from ai_employee.db.models import Approval
from ai_employee.execution import approvals, queue
from ai_employee.execution.approvals import (
    AlreadyDecidedError,
    ApprovalNotFoundError,
    NotApproverError,
)

router = APIRouter()

CurrentIdentity = Annotated[Identity, Depends(current_identity)]


def _decide(
    identity: Identity, approval_id: uuid.UUID, approved: bool, reason: str | None
) -> Approval:
    try:
        return approvals.decide(
            identity.tenant_id, approval_id, identity.user_id, approved=approved, reason=reason
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NotApproverError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except AlreadyDecidedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/api/approvals", response_model=list[ApprovalView])
def list_pending(identity: CurrentIdentity) -> list[ApprovalView]:
    """What the coworker is waiting for this user to confirm."""
    return [ApprovalView.of(a) for a in approvals.pending_for(identity.tenant_id, identity.user_id)]


@router.post("/api/approvals/{approval_id}/approve", response_model=ApprovalView)
def approve(
    approval_id: uuid.UUID, identity: CurrentIdentity, body: DecisionRequest | None = None
) -> ApprovalView:
    return ApprovalView.of(_decide(identity, approval_id, True, body.reason if body else None))


@router.post("/api/approvals/{approval_id}/reject", response_model=ApprovalView)
def reject(
    approval_id: uuid.UUID, identity: CurrentIdentity, body: DecisionRequest | None = None
) -> ApprovalView:
    return ApprovalView.of(_decide(identity, approval_id, False, body.reason if body else None))


@router.post("/chat/approvals/{approval_id}/{verdict}", response_class=HTMLResponse)
def chat_decide(
    request: Request, approval_id: uuid.UUID, verdict: str, identity: CurrentIdentity
) -> Response:
    if verdict not in ("approve", "reject"):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    approval = _decide(identity, approval_id, verdict == "approve", None)
    task = queue.get(identity.tenant_id, approval.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return templates.TemplateResponse(request, "_reply.html", reply_context(identity, task))
