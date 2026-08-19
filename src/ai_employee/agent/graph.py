"""LangGraph agent: agent node -> tool node -> loop."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from ai_employee.agent.prompts import SYSTEM_PROMPT
from ai_employee.config import get_settings
from ai_employee.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

# Each tool round trip costs two steps (agent, tools). This caps the loop at roughly five
# searches before LangGraph raises, which is well past any legitimate question.
RECURSION_LIMIT = 12


class AgentNotConfiguredError(RuntimeError):
    """Raised when the Azure OpenAI settings needed to run the agent are missing."""


@lru_cache
def _model() -> BaseChatModel:
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("AZURE_OPENAI_API_KEY", settings.azure_openai_api_key),
            ("AZURE_OPENAI_ENDPOINT", settings.azure_openai_endpoint),
            ("AZURE_OPENAI_DEPLOYMENT", settings.azure_openai_deployment),
        )
        if not value
    ]
    if missing:
        raise AgentNotConfiguredError(f"missing required settings: {', '.join(missing)}")

    model = AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
        # Deterministic: grounded answers should not vary run to run, and the eval harness
        # depends on repeatability.
        temperature=0,
    )
    return model.bind_tools(ALL_TOOLS)


def agent_node(state: MessagesState) -> dict[str, Any]:
    """Call the model. The system prompt is prepended per turn rather than stored in state,
    so editing it takes effect on existing conversations."""
    messages = [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
    return {"messages": [_model().invoke(messages)]}


@lru_cache
def build_graph():
    """Compile the agent graph. Cached so the checkpointer survives across calls."""
    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(ALL_TOOLS))

    builder.add_edge(START, "agent")
    # tools_condition routes to "tools" when the model emitted tool calls, otherwise to END.
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    # In-process memory: conversation state is lost on restart and not shared between
    # workers. Replace with a Postgres checkpointer before this runs anywhere real.
    return builder.compile(checkpointer=InMemorySaver())


def config_for(thread_id: str) -> dict[str, Any]:
    """Invocation config. thread_id selects the conversation the checkpointer resumes."""
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}