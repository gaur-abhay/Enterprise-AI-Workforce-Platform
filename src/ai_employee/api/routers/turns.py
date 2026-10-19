"""Turns over REST, and the chat page that drives them."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ai_employee.api.identity import DevLogin, Identity, current_identity, optional_identity
from ai_employee.api.schemas.turns import TaskAccepted, TaskView, TurnRequest
from ai_employee.api.views import reply_context, templates
from ai_employee.db.models import TaskStatus, TurnTask
from ai_employee.execution import queue
from ai_employee.observability import current_request_id

router = APIRouter()

CurrentIdentity = Annotated[Identity, Depends(current_identity)]


def _enqueue(identity: Identity, message: str) -> uuid.UUID:
    request_id = current_request_id() or uuid.uuid4().hex
    return queue.enqueue(identity.turn_context(request_id), message)


def _task(identity: Identity, task_id: uuid.UUID) -> TurnTask:
    task = queue.get(identity.tenant_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such turn")
    return task


@router.post("/api/turns", status_code=status.HTTP_202_ACCEPTED, response_model=TaskAccepted)
def create_turn(body: TurnRequest, identity: CurrentIdentity) -> TaskAccepted:
    """Accept the turn and queue it; a worker runs it. Poll the returned task."""
    task_id = _enqueue(identity, body.message)
    return TaskAccepted(task_id=task_id, status=TaskStatus.QUEUED)


@router.get("/api/turns/{task_id}", response_model=TaskView)
def read_turn(task_id: uuid.UUID, identity: CurrentIdentity) -> TaskView:
    return TaskView.of(_task(identity, task_id))


@router.get("/", response_class=HTMLResponse)
def chat_page(request: Request) -> Response:
    identity = optional_identity(request)
    if identity is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "chat.html", {"identity": identity})


@router.post("/chat", response_class=HTMLResponse)
def chat_turn(
    request: Request, identity: CurrentIdentity, message: Annotated[str, Form(max_length=4000)]
) -> Response:
    task = _task(identity, _enqueue(identity, message))
    return templates.TemplateResponse(request, "_turn.html", reply_context(identity, task))


@router.get("/chat/turns/{task_id}", response_class=HTMLResponse)
def chat_turn_status(request: Request, task_id: uuid.UUID, identity: CurrentIdentity) -> Response:
    task = _task(identity, task_id)
    return templates.TemplateResponse(request, "_reply.html", reply_context(identity, task))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    return templates.TemplateResponse(request, "login.html", {"users": DevLogin.users()})


@router.post("/login")
def login(request: Request, user_id: Annotated[uuid.UUID, Form()]) -> Response:
    if not DevLogin.sign_in(request, user_id):
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request) -> Response:
    DevLogin.sign_out(request)
    return RedirectResponse("/login", status_code=303)
