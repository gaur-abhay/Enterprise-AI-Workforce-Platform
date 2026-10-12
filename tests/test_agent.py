"""run_turn with a scripted chat model: tools go through the dispatcher, sources surface."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from sqlalchemy import select

from ai_employee.agent import graph, run_turn, runner
from ai_employee.cli.seed import TenantSeed, seed_tenant
from ai_employee.context import TurnContext
from ai_employee.db import admin_session, tenant_session
from ai_employee.db.models import Employee, ToolCall
from ai_employee.tools import search_documents as search_tool

HIT = {"chunk_id": "c1", "source": "policy.md", "content": "Hotels capped at 250 EUR."}


class ScriptedModel(BaseChatModel):
    """Replays a fixed list of replies and records what it was shown."""

    replies: list[AIMessage]
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedModel:  # type: ignore[override]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        reply = self.replies.pop(0) if self.replies else AIMessage("out of script")
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _call(name: str, args: dict[str, Any], call_id: str = "t1") -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])


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
        correlation_id="turn-1",
    )


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(search_tool, "search", lambda c, q, k: [_Hit(HIT)])

    def install(*replies: AIMessage) -> ScriptedModel:
        model = ScriptedModel(replies=list(replies), seen=[])
        monkeypatch.setattr(graph, "get_chat_model", lambda: model)
        return model

    yield install


class _Hit:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def as_dict(self) -> dict[str, Any]:
        return self.data


def test_search_then_answer(ctx: TurnContext, script: Any) -> None:
    model = script(
        _call("search_documents", {"query": "hotel cap"}),
        AIMessage("Hotels are capped at 250 EUR (policy.md)."),
    )

    result = run_turn(ctx, "What is the hotel cap?")

    assert result.answer == "Hotels are capped at 250 EUR (policy.md)."
    assert result.sources == [HIT]
    assert result.tool_calls == [{"name": "search_documents", "args": {"query": "hotel cap"}}]
    # The second model call saw the tool output.
    tool_message = model.seen[1][-1]
    assert isinstance(tool_message, ToolMessage) and "250 EUR" in str(tool_message.content)
    with tenant_session(ctx.tenant_id) as session:
        [audit] = session.scalars(select(ToolCall)).all()
    assert audit.correlation_id == "turn-1"


def test_employee_name_is_in_the_system_prompt(ctx: TurnContext, script: Any) -> None:
    model = script(AIMessage("Hello."))

    assert run_turn(ctx, "hi").answer == "Hello."
    assert "You are Coworker" in str(model.seen[0][0].content)


def test_tool_errors_are_fed_back_to_the_model(ctx: TurnContext, script: Any) -> None:
    model = script(_call("delete_everything", {}), AIMessage("I can't do that."))

    result = run_turn(ctx, "delete it all")

    assert result.answer == "I can't do that."
    feedback = model.seen[1][-1]
    assert isinstance(feedback, ToolMessage) and "unknown tool" in str(feedback.content)


def test_runaway_loop_is_cut_off(ctx: TurnContext, script: Any) -> None:
    script(*[_call("search_documents", {"query": "x"}, f"t{i}") for i in range(20)])

    assert run_turn(ctx, "loop").answer == runner.GAVE_UP
