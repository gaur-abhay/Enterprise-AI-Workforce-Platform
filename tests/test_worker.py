"""Queue and worker: claiming, leases, retries, and resuming a turn from its checkpoint."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select, update

from ai_employee.agent import TurnResult, graph, run_turn
from ai_employee.cli.seed import TenantSeed, seed_tenant
from ai_employee.context import TurnContext
from ai_employee.db import admin_session
from ai_employee.db.models import Employee, TaskStatus, TurnTask
from ai_employee.execution import queue
from ai_employee.execution.checkpointer import open_checkpointer
from ai_employee.execution.worker import Worker
from ai_employee.tools import Ok
from tests.test_agent import ScriptedModel

LEASE = timedelta(seconds=30)


@pytest.fixture
def ctx(clean_db: None) -> TurnContext:
    with admin_session() as session:
        tenant = seed_tenant(session, TenantSeed(slug="alpha", name="Alpha"))
        employee = session.scalars(select(Employee)).one()
    return TurnContext(
        tenant_id=tenant.id,
        employee_id=employee.id,
        actor=employee.id,
        trigger="api",
        correlation_id="corr-q",
    )


@pytest.fixture
def checkpointer(database: str) -> Iterator[PostgresSaver]:
    with open_checkpointer() as saver:
        yield saver


def _task(task_id: Any) -> TurnTask:
    with admin_session() as session:
        return session.get_one(TurnTask, task_id)


def _answer(ctx: TurnContext, message: str, **_: Any) -> TurnResult:
    return TurnResult(answer=f"re: {message}")


def test_enqueued_turn_is_run_and_recorded(ctx: TurnContext) -> None:
    task_id = queue.enqueue(ctx, "hello")
    worker = Worker(run=_answer)

    assert worker.run_once(None) is True
    task = _task(task_id)
    assert task.status is TaskStatus.SUCCEEDED
    assert task.result == {"answer": "re: hello", "sources": [], "tool_calls": []}
    assert worker.run_once(None) is False


def test_context_round_trips_through_the_queue(ctx: TurnContext) -> None:
    seen: list[TurnContext] = []
    queue.enqueue(ctx, "hi")

    Worker(run=lambda c, m, **_: seen.append(c) or TurnResult(answer="ok")).run_once(None)

    assert seen == [ctx]


def test_a_claimed_task_is_not_claimed_twice(ctx: TurnContext) -> None:
    queue.enqueue(ctx, "once")

    assert queue.claim_next("w1", LEASE) is not None
    assert queue.claim_next("w2", LEASE) is None


def test_an_expired_lease_is_reclaimed(ctx: TurnContext) -> None:
    task_id = queue.enqueue(ctx, "orphan")
    queue.claim_next("dead-worker", LEASE)
    with admin_session() as session:
        session.execute(
            update(TurnTask).values(lease_expires_at=TurnTask.lease_expires_at - LEASE * 2)
        )

    reclaimed = queue.claim_next("w2", LEASE)

    assert reclaimed is not None and reclaimed.id == task_id
    assert (reclaimed.claimed_by, reclaimed.attempts) == ("w2", 2)
    # The dead worker can no longer write to it.
    queue.complete(task_id, "dead-worker", {"answer": "stale"})
    assert _task(task_id).status is TaskStatus.RUNNING


def test_failures_retry_then_stop(ctx: TurnContext) -> None:
    task_id = queue.enqueue(ctx, "boom")

    def explode(*_: Any, **__: Any) -> TurnResult:
        raise RuntimeError("model unavailable")

    worker = Worker(run=explode)
    for _ in range(queue.MAX_ATTEMPTS):
        worker.run_once(None)

    task = _task(task_id)
    assert (task.status, task.attempts) == (TaskStatus.FAILED, queue.MAX_ATTEMPTS)
    assert task.error == "RuntimeError: model unavailable"
    assert worker.run_once(None) is False


def test_turn_resumes_from_its_checkpoint_after_a_crash(
    ctx: TurnContext, checkpointer: PostgresSaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = ScriptedModel(
        replies=[
            AIMessage(
                "", tool_calls=[{"name": "search_documents", "args": {"query": "q"}, "id": "t1"}]
            ),
            AIMessage("final answer"),
        ],
        seen=[],
    )
    monkeypatch.setattr(graph, "get_chat_model", lambda: model)
    calls = {"n": 0}

    def flaky_dispatch(*_: Any, **__: Any) -> Ok:
        calls["n"] += 1
        if calls["n"] == 1:
            raise SystemExit("worker killed mid-tool")
        return Ok([])

    monkeypatch.setattr(graph, "dispatch", flaky_dispatch)
    thread = "thread-resume"

    with pytest.raises(SystemExit):
        run_turn(ctx, "question", checkpointer=checkpointer, thread_id=thread)
    result = run_turn(ctx, "question", checkpointer=checkpointer, thread_id=thread)

    assert result.answer == "final answer"
    # The first model step was checkpointed, so the resume did not call the model for it again.
    assert len(model.seen) == 2
    # And a finished thread returns its result without running anything.
    assert run_turn(ctx, "question", checkpointer=checkpointer, thread_id=thread).answer == (
        "final answer"
    )
    assert len(model.seen) == 2
