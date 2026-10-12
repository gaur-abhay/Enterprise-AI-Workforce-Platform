"""run_turn: the single entry point every channel calls. No HTTP, no channel types."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from ai_employee.agent.graph import RECURSION_LIMIT, build_graph
from ai_employee.agent.prompts import system_prompt
from ai_employee.context import TurnContext
from ai_employee.db import tenant_session
from ai_employee.db.models import Employee
from ai_employee.observability import request_context, truncate

logger = logging.getLogger(__name__)

GAVE_UP = "I could not reach an answer within the allowed number of steps. Try a narrower question."


@dataclass(frozen=True)
class TurnResult:
    answer: str
    # Passages retrieved during the turn, deduplicated; the answer may cite a subset.
    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def _dedupe(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({s["chunk_id"]: s for s in sources}.values())


def run_turn(ctx: TurnContext, message: str) -> TurnResult:
    """Run one agent turn for the given context."""
    with request_context(ctx.correlation_id):
        started = time.perf_counter()
        logger.info("turn start tenant=%s: %r", ctx.tenant_id, truncate(message))

        with tenant_session(ctx.tenant_id) as session:
            employee = session.get_one(Employee, ctx.employee_id)
            prompt = system_prompt(employee.name, employee.instructions)

        graph = build_graph(ctx, prompt)
        try:
            state = graph.invoke(
                {"messages": [HumanMessage(message)], "sources": []},
                config={"recursion_limit": RECURSION_LIMIT},
            )
        except GraphRecursionError:
            logger.warning("turn hit the recursion limit")
            return TurnResult(answer=GAVE_UP)

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
