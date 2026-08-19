"""Convenience entrypoint for driving the agent outside the API."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from ai_employee.agent.graph import AgentNotConfiguredError, build_graph, config_for
from ai_employee.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class AgentAnswer:
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    messages: list[BaseMessage] = field(default_factory=list)


def _extract_sources(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Collect the passages the model was shown, from the retrieval tool's JSON output.

    These are what was retrieved, not necessarily what the answer used - the model may cite a
    subset. Treated as an audit trail rather than a citation list.
    """
    seen: dict[str, dict[str, Any]] = {}
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            payload = json.loads(message.content)
        except (TypeError, ValueError):
            logger.debug("tool message %s was not JSON", message.tool_call_id)
            continue
        for hit in payload.get("results", []):
            chunk_id = hit.get("chunk_id")
            if chunk_id and chunk_id not in seen:
                seen[chunk_id] = {
                    "chunk_id": chunk_id,
                    "source": hit.get("source"),
                    "page": hit.get("page"),
                    "score": hit.get("score"),
                }
    return list(seen.values())


def ask(question: str, thread_id: str = "default") -> AgentAnswer:
    """Run one turn. Passing the same thread_id continues an existing conversation."""
    state = build_graph().invoke(
        {"messages": [HumanMessage(content=question)]},
        config=config_for(thread_id),
    )

    messages = state["messages"]
    tool_calls = [call for m in messages if isinstance(m, AIMessage) for call in m.tool_calls]
    return AgentAnswer(
        answer=messages[-1].content,
        sources=_extract_sources(messages),
        tool_calls=tool_calls,
        messages=messages,
    )


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