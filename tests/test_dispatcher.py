"""Dispatcher: every call validated, policed, executed or held, and audited."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from ai_employee.cli.seed import TenantSeed, seed_tenant
from ai_employee.context import TurnContext
from ai_employee.db import admin_session, tenant_session
from ai_employee.db.models import Employee, SideEffectClass, ToolCall, ToolOutcome
from ai_employee.tools import Decision, Error, Ok, PendingApproval, dispatch, dispatcher, registry
from ai_employee.tools import search_documents as search_tool
from ai_employee.tools.registry import ToolDeclaration


class EchoInput(BaseModel):
    text: str


class Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, ctx: TurnContext, args: EchoInput, credential: Any) -> str:
        self.calls.append(args.text)
        if args.text == "boom":
            raise RuntimeError("internal detail")
        return args.text.upper()


@pytest.fixture
def ctx(clean_db: None) -> TurnContext:
    with admin_session() as session:
        tenant = seed_tenant(session, TenantSeed(slug="alpha", name="Alpha"))
        employee = session.scalars(select(Employee)).one()
    return TurnContext(
        tenant_id=tenant.id,
        employee_id=employee.id,
        actor="system",
        trigger="api",
        correlation_id="corr-1",
    )


@pytest.fixture
def tool(monkeypatch: pytest.MonkeyPatch) -> Any:
    def make(cls: SideEffectClass, connection_type: str | None = None) -> Recorder:
        recorder = Recorder()
        declaration = ToolDeclaration(
            name="echo",
            description="Echo",
            input_model=EchoInput,
            side_effect_class=cls,
            handler=recorder,
            connection_type=connection_type,
        )
        monkeypatch.setitem(registry._REGISTRY, "echo", declaration)
        return recorder

    return make


def _audit(ctx: TurnContext) -> list[ToolCall]:
    with tenant_session(ctx.tenant_id) as session:
        return list(session.scalars(select(ToolCall)))


def test_read_tool_runs_and_is_audited(ctx: TurnContext, tool: Any) -> None:
    tool(SideEffectClass.READ)

    assert dispatch(ctx, "echo", {"text": "hi"}) == Ok("HI")
    [row] = _audit(ctx)
    assert (row.tool_name, row.outcome, row.arguments) == ("echo", ToolOutcome.OK, {"text": "hi"})
    assert (row.correlation_id, row.actor) == ("corr-1", "system")


def test_invalid_arguments_are_returned_to_the_model(ctx: TurnContext, tool: Any) -> None:
    recorder = tool(SideEffectClass.READ)

    result = dispatch(ctx, "echo", {"wrong": 1})

    assert isinstance(result, Error) and "invalid arguments" in result.message
    assert recorder.calls == []
    assert _audit(ctx)[0].outcome is ToolOutcome.ERROR


def test_unknown_tool_is_an_audited_error(ctx: TurnContext) -> None:
    assert dispatch(ctx, "nope", {}) == Error("unknown tool 'nope'")
    [row] = _audit(ctx)
    assert row.side_effect_class is None


@pytest.mark.parametrize("cls", [SideEffectClass.WRITE, SideEffectClass.IRREVERSIBLE])
def test_side_effects_are_held_for_approval(
    ctx: TurnContext, tool: Any, cls: SideEffectClass
) -> None:
    recorder = tool(cls)

    assert dispatch(ctx, "echo", {"text": "x"}) == PendingApproval("echo", {"text": "x"})
    assert recorder.calls == []
    assert _audit(ctx)[0].outcome is ToolOutcome.PENDING_APPROVAL


def test_irreversible_ignores_a_permissive_policy(
    ctx: TurnContext, tool: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatcher, "WRITE_REQUIRES_APPROVAL", False)
    tool(SideEffectClass.IRREVERSIBLE)

    assert isinstance(dispatch(ctx, "echo", {"text": "x"}), PendingApproval)


def test_handler_failure_hides_internals(ctx: TurnContext, tool: Any) -> None:
    tool(SideEffectClass.READ)

    result = dispatch(ctx, "echo", {"text": "boom"})

    assert isinstance(result, Error) and "internal detail" not in result.message
    assert _audit(ctx)[0].outcome is ToolOutcome.ERROR


def test_missing_credential_is_an_error(ctx: TurnContext, tool: Any) -> None:
    recorder = tool(SideEffectClass.READ, connection_type="github")

    assert dispatch(ctx, "echo", {"text": "x"}) == Error("no github connection available")
    assert recorder.calls == []


def test_audit_rows_cannot_be_rewritten(ctx: TurnContext, tool: Any) -> None:
    tool(SideEffectClass.READ)
    dispatch(ctx, "echo", {"text": "hi"})

    with (
        pytest.raises(DBAPIError, match="permission denied"),
        tenant_session(ctx.tenant_id) as session,
    ):
        session.execute(update(ToolCall).values(outcome=ToolOutcome.ERROR))


def test_search_documents_goes_through_the_dispatcher(
    ctx: TurnContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(search_tool, "search", lambda c, q, k: seen.append((q, k)) or [])

    assert dispatch(ctx, "search_documents", {"query": "refunds", "top_k": 3}) == Ok([])
    assert seen == [("refunds", 3)]
    assert _audit(ctx)[0].side_effect_class is SideEffectClass.READ


def test_an_approved_call_runs(ctx: TurnContext, tool: Any) -> None:
    recorder = tool(SideEffectClass.WRITE)

    assert dispatch(ctx, "echo", {"text": "x"}, decision=Decision(approved=True)) == Ok("X")
    assert recorder.calls == ["x"]


def test_a_declined_call_does_not_run(ctx: TurnContext, tool: Any) -> None:
    recorder = tool(SideEffectClass.WRITE)

    result = dispatch(ctx, "echo", {"text": "x"}, decision=Decision(approved=False, reason="no"))

    assert isinstance(result, Error) and "declined echo: no" in result.message
    assert recorder.calls == []
    assert _audit(ctx)[0].outcome is ToolOutcome.ERROR


def test_invalid_held_calls_are_not_sent_for_approval(tool: Any) -> None:
    tool(SideEffectClass.WRITE)

    assert dispatcher.needs_approval("echo", {"text": "x"}) is True
    assert dispatcher.needs_approval("echo", {"wrong": 1}) is False
    assert dispatcher.needs_approval("nope", {}) is False
