"""Agent graph: model -> tools -> model, with every tool call routed through the dispatcher."""

from __future__ import annotations

import json
import operator
from typing import Annotated, Any

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolCall, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import tools_condition
from langgraph.types import interrupt
from typing_extensions import TypedDict

from ai_employee.context import TurnContext
from ai_employee.llm import get_chat_model
from ai_employee.tools import (
    Decision,
    Error,
    Ok,
    PendingApproval,
    dispatch,
    needs_approval,
    registry,
)

# Two steps per tool round trip; roughly five searches before the loop is cut off.
RECURSION_LIMIT = 12


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    # Passages returned by search_documents during the turn, for citation display.
    sources: Annotated[list[dict[str, Any]], operator.add]


def _tool_message(call_id: str, result: Ok | Error | PendingApproval) -> ToolMessage:
    match result:
        case Ok(value):
            return ToolMessage(json.dumps(value, default=str), tool_call_id=call_id)
        case Error(message):
            return ToolMessage(f"error: {message}", tool_call_id=call_id, status="error")
        case PendingApproval(tool_name, _):
            return ToolMessage(
                f"{tool_name} needs the user's confirmation, which this channel cannot "
                "collect; tell the user the action was not taken.",
                tool_call_id=call_id,
            )


def _call_id(call: ToolCall, index: int) -> str:
    return call["id"] or f"{call['name']}-{index}"


def build_graph(
    ctx: TurnContext, system_prompt: str, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[Any]:
    """Compile a graph bound to one turn's context."""
    tools = registry.available(ctx)
    model = get_chat_model().bind_tools([t.spec() for t in tools])

    def agent(state: AgentState) -> dict[str, Any]:
        return {"messages": [model.invoke([SystemMessage(system_prompt), *state["messages"]])]}

    def run_tools(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        calls = [(_call_id(c, i), c) for i, c in enumerate(last.tool_calls)]

        decisions: dict[str, Decision] = {}
        held = [(cid, c) for cid, c in calls if needs_approval(c["name"], c["args"])]
        if held and checkpointer is not None:
            # Nothing above this line may have side effects: on resume the node re-runs from
            # the top, and interrupt() returns the requester's answers instead of pausing.
            answers = interrupt(
                [
                    {"tool_call_id": cid, "tool_name": c["name"], "arguments": c["args"]}
                    for cid, c in held
                ]
            )
            decisions = {cid: Decision(**answer) for cid, answer in answers.items()}

        messages, sources = [], []
        for cid, call in calls:
            result = dispatch(ctx, call["name"], call["args"], decision=decisions.get(cid))
            if call["name"] == "search_documents" and isinstance(result, Ok):
                sources.extend(result.value)
            messages.append(_tool_message(cid, result))
        return {"messages": messages, "sources": sources}

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent)
    builder.add_node("tools", run_tools)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)
