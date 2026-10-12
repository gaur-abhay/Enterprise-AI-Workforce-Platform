"""Turns over REST, and the chat page that drives them."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ai_employee.agent import TurnResult, run_turn
from ai_employee.api.identity import DevLogin, Identity, current_identity, optional_identity
from ai_employee.api.schemas.turns import Source, TurnRequest, TurnResponse
from ai_employee.observability import current_request_id

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

CurrentIdentity = Annotated[Identity, Depends(current_identity)]


def _run(identity: Identity, message: str) -> tuple[str, TurnResult]:
    request_id = current_request_id() or uuid.uuid4().hex
    return request_id, run_turn(identity.turn_context(request_id), message)


@router.post("/api/turns", response_model=TurnResponse)
def create_turn(body: TurnRequest, identity: CurrentIdentity) -> TurnResponse:
    """Run one turn synchronously. Becomes accept-and-enqueue with the worker."""
    request_id, result = _run(identity, body.message)
    return TurnResponse(
        answer=result.answer,
        request_id=request_id,
        sources=[Source(**s) for s in result.sources],
        tool_calls=result.tool_calls,
    )


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
    request_id, result = _run(identity, message)
    return templates.TemplateResponse(
        request, "_turn.html", {"message": message, "result": result, "request_id": request_id}
    )


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
