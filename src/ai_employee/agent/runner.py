"""Convenience entrypoint for driving the agent outside the API."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ai_employee.agent.graph import AgentNotConfiguredError, build_graph, config_for
from ai_employee.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class AgentAnswer:
    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    messages: list[BaseMessage] = field(default_factory=list)


def ask(question: str, thread_id: str = "default") -> AgentAnswer:
    """Run one turn. Passing the same thread_id continues an existing conversation."""
    state = build_graph().invoke(
        {"messages": [HumanMessage(content=question)]},
        config=config_for(thread_id),
    )

    messages = state["messages"]
    tool_calls = [call for m in messages if isinstance(m, AIMessage) for call in m.tool_calls]
    return AgentAnswer(answer=messages[-1].content, tool_calls=tool_calls, messages=messages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask the agent a question.")
    parser.add_argument("question")
    parser.add_argument("--thread", default="cli", help="conversation id (default: cli)")
    parser.add_argument("--show-tools", action="store_true", help="print the tool calls made")
    args = parser.parse_args(argv)

    logging.basicConfig(level=get_settings().log_level, format="%(levelname)s %(name)s: %(message)s")

    try:
        result = ask(args.question, thread_id=args.thread)
    except AgentNotConfiguredError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.show_tools:
        for call in result.tool_calls:
            print(f"[tool] {call['name']}({call['args']})", file=sys.stderr)
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())