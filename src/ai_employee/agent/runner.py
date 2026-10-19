"""run_turn: the single entry point every channel calls. No HTTP, no channel types."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command, Interrupt

from ai_employee.agent.graph import RECURSION_LIMIT, build_graph
from ai_employee.agent.prompts import system_prompt
from ai_employee.context import TurnContext
from ai_employee.db import tenant_session
from ai_employee.db.models import Employee
from ai_employee.observability import request_context, truncate
from ai_employee.tools import Decision

logger = logging.getLogger(__name__)

GAVE_UP = "I could not reach an answer within the allowed number of steps. Try a narrower question."


@dataclass(frozen=True)
class TurnResult:
    answer: str
    # Passages retrieved during the turn, deduplicated; the answer may cite a subset.
    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ApprovalRequest:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class TurnSuspended:
    """The turn paused for the requester to confirm these calls. Resume with their decisions."""

    requests: list[ApprovalRequest]


TurnOutcome = TurnResult | TurnSuspended


def _dedupe(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({s["chunk_id"]: s for s in sources}.values())


def run_turn(
    ctx: TurnContext,
    message: str,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    thread_id: str | None = None,
    decisions: dict[str, Decision] | None = None,
) -> TurnOutcome:
    """Run one agent turn for the given context.

    With a checkpointer, state is saved after every step under `thread_id`; calling again
    with the same thread resumes from the last completed step instead of starting over. A
    turn that reaches a call needing confirmation returns TurnSuspended; calling again with
    `decisions` (keyed by tool call id) continues it from that point.
    """
    with request_context(ctx.correlation_id):
        started = time.perf_counter()
        logger.info("turn start tenant=%s: %r", ctx.tenant_id, truncate(message))

        with tenant_session(ctx.tenant_id) as session:
            employee = session.get_one(Employee, ctx.employee_id)
            prompt = system_prompt(employee.name, employee.instructions)

        graph = build_graph(ctx, prompt, checkpointer)
        config: RunnableConfig = {"recursion_limit": RECURSION_LIMIT}
        initial: Any = {"messages": [HumanMessage(message)], "sources": []}
        if checkpointer is not None:
            if thread_id is None:
                raise ValueError("a checkpointed turn needs a thread_id")
            config["configurable"] = {"thread_id": thread_id}
            snapshot = graph.get_state(config)
            if snapshot.values:
                logger.info("resuming turn from checkpoint, next=%s", snapshot.next)
                if not snapshot.next:
                    return _result(snapshot.values, started)
                if snapshot.interrupts:
                    if decisions is None:
                        return _suspended(snapshot.interrupts)
                    initial = Command(resume={k: asdict(v) for k, v in decisions.items()})
                else:
                    initial = None

        try:
            if checkpointer is None:
                state = graph.invoke(initial, config=config)
            else:
                # sync: each step's checkpoint is durable before the next step starts.
                state = graph.invoke(initial, config=config, durability="sync")
        except GraphRecursionError:
            logger.warning("turn hit the recursion limit")
            return TurnResult(answer=GAVE_UP)

        if state.get("__interrupt__"):
            return _suspended(state["__interrupt__"])
        return _result(state, started)


def _suspended(interrupts: Sequence[Interrupt]) -> TurnSuspended:
    requests = [ApprovalRequest(**request) for i in interrupts for request in i.value]
    logger.info("turn suspended for %d confirmation(s)", len(requests))
    return TurnSuspended(requests)


def _result(state: dict[str, Any], started: float) -> TurnResult:
    messages = state["messages"]
    result = TurnResult(
        answer=messages[-1].text,
        sources=_dedupe(state["sources"]),
        tool_calls=[
            {"name": c["name"], "args": c["args"]}
            for m in messages
            if isinstance(m, AIMessage)
            for c in m.tool_calls
        ],
    )
    logger.info(
        "turn done in %.2fs: %d tool call(s), %d source(s)",
        time.perf_counter() - started,
        len(result.tool_calls),
        len(result.sources),
    )
    return result
