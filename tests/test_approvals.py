"""Seam 2: a turn pauses for the requester's confirmation and a different worker resumes it."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select

from ai_employee.agent import ApprovalRequest, graph
from ai_employee.cli.seed import TenantSeed, seed_tenant
from ai_employee.context import TurnContext
from ai_employee.db import admin_session, tenant_session
from ai_employee.db.models import (
    Approval,
    ApprovalStatus,
    Employee,
    OutboxMessage,
    TaskStatus,
    ToolCall,
    ToolOutcome,
    TurnTask,
    User,
    UserRole,
)
from ai_employee.execution import approvals, queue
from ai_employee.execution.approvals import AlreadyDecidedError, NotApproverError
from ai_employee.execution.checkpointer import open_checkpointer
from ai_employee.execution.worker import Worker
from tests.test_agent import ScriptedModel

EMAIL = {"to": "finance@alpha.example", "subject": "Q3 numbers", "body": "Please send Q3."}


@pytest.fixture
def people(clean_db: None) -> dict[str, Any]:
    with admin_session() as session:
        tenant = seed_tenant(session, TenantSeed(slug="alpha", name="Alpha"))
        employee = session.scalars(select(Employee)).one()
        users = {u.role: u.id for u in session.scalars(select(User))}
    return {
        "tenant": tenant.id,
        "member": users[UserRole.MEMBER],
        "admin": users[UserRole.ADMIN],
        "ctx": TurnContext(
            tenant_id=tenant.id,
            employee_id=employee.id,
            actor=users[UserRole.MEMBER],
            trigger="api",
            correlation_id="corr-approve",
        ),
    }


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> ScriptedModel:
    scripted = ScriptedModel(
        replies=[
            AIMessage("", tool_calls=[{"name": "send_email", "args": EMAIL, "id": "call-1"}]),
            AIMessage("Done."),
        ],
        seen=[],
    )
    monkeypatch.setattr(graph, "get_chat_model", lambda: scripted)
    return scripted


@pytest.fixture
def two_checkpointers(database: str) -> Iterator[tuple[PostgresSaver, PostgresSaver]]:
    # Separate connections, standing in for two worker processes.
    with open_checkpointer() as first, open_checkpointer() as second:
        yield first, second


def _task(task_id: Any) -> TurnTask:
    with admin_session() as session:
        return session.get_one(TurnTask, task_id)


def _approval(tenant_id: Any) -> Approval:
    with tenant_session(tenant_id) as session:
        return session.scalars(select(Approval)).one()


def _outbox(tenant_id: Any) -> list[OutboxMessage]:
    with tenant_session(tenant_id) as session:
        return list(session.scalars(select(OutboxMessage)))


def _suspend(people: dict[str, Any], checkpointer: PostgresSaver) -> Any:
    task_id = queue.enqueue(people["ctx"], "Email finance for the Q3 numbers")
    assert Worker(worker_id="worker-a").run_once(checkpointer)
    return task_id


def test_turn_pauses_and_a_different_worker_resumes_it(
    people: dict[str, Any], model: ScriptedModel, two_checkpointers: Any
) -> None:
    first, second = two_checkpointers
    task_id = _suspend(people, first)

    # Paused: nothing sent, the exact call is held for the requester.
    assert _task(task_id).status is TaskStatus.AWAITING_APPROVAL
    approval = _approval(people["tenant"])
    assert (approval.tool_name, approval.arguments) == ("send_email", EMAIL)
    assert approval.approver == str(people["member"])
    assert _outbox(people["tenant"]) == []

    approvals.decide(people["tenant"], approval.id, people["member"], approved=True)
    assert _task(task_id).status is TaskStatus.QUEUED

    assert Worker(worker_id="worker-b").run_once(second)
    task = _task(task_id)
    assert task.status is TaskStatus.SUCCEEDED
    assert task.result and task.result["answer"] == "Done."
    [sent] = _outbox(people["tenant"])
    assert (sent.recipient, sent.sent_by) == ("finance@alpha.example", str(people["member"]))
    # The first model step came from the checkpoint, not a second model call.
    assert len(model.seen) == 2
    with tenant_session(people["tenant"]) as session:
        outcomes = [
            c.outcome for c in session.scalars(select(ToolCall).order_by(ToolCall.created_at))
        ]
    assert outcomes == [ToolOutcome.PENDING_APPROVAL, ToolOutcome.OK]


def test_declined_call_is_not_run_and_the_model_is_told(
    people: dict[str, Any], model: ScriptedModel, two_checkpointers: Any
) -> None:
    first, second = two_checkpointers
    task_id = _suspend(people, first)
    approval = _approval(people["tenant"])

    approvals.decide(
        people["tenant"], approval.id, people["member"], approved=False, reason="wrong person"
    )
    Worker(worker_id="worker-b").run_once(second)

    assert _task(task_id).status is TaskStatus.SUCCEEDED
    assert _outbox(people["tenant"]) == []
    feedback = model.seen[1][-1]
    assert isinstance(feedback, ToolMessage)
    assert "declined send_email: wrong person" in str(feedback.content)


def test_only_the_requester_can_confirm(
    people: dict[str, Any], model: ScriptedModel, two_checkpointers: Any
) -> None:
    _suspend(people, two_checkpointers[0])
    approval = _approval(people["tenant"])

    with pytest.raises(NotApproverError):
        approvals.decide(people["tenant"], approval.id, people["admin"], approved=True)
    assert _approval(people["tenant"]).status is ApprovalStatus.PENDING


def test_a_decision_is_final(
    people: dict[str, Any], model: ScriptedModel, two_checkpointers: Any
) -> None:
    _suspend(people, two_checkpointers[0])
    approval = _approval(people["tenant"])
    approvals.decide(people["tenant"], approval.id, people["member"], approved=False)

    with pytest.raises(AlreadyDecidedError):
        approvals.decide(people["tenant"], approval.id, people["member"], approved=True)


def test_recording_a_suspension_twice_adds_nothing(
    people: dict[str, Any], model: ScriptedModel, two_checkpointers: Any
) -> None:
    task_id = _suspend(people, two_checkpointers[0])
    request = ApprovalRequest(tool_call_id="call-1", tool_name="send_email", arguments=EMAIL)

    approvals.record(_task(task_id), people["ctx"], [request])

    with tenant_session(people["tenant"]) as session:
        assert len(session.scalars(select(Approval)).all()) == 1
        assert len(session.scalars(select(ToolCall)).all()) == 1


def test_a_suspended_turn_is_not_claimed(
    people: dict[str, Any], model: ScriptedModel, two_checkpointers: Any
) -> None:
    _suspend(people, two_checkpointers[0])

    assert Worker(worker_id="worker-b").run_once(two_checkpointers[1]) is False


def test_requester_confirms_over_http(
    people: dict[str, Any], model: ScriptedModel, two_checkpointers: Any
) -> None:
    from fastapi.testclient import TestClient

    from ai_employee.api import main

    task_id = _suspend(people, two_checkpointers[0])
    client = TestClient(main.app)

    client.post("/login", data={"user_id": str(people["admin"])})
    approval_id = _approval(people["tenant"]).id
    assert client.get("/api/approvals").json() == []
    assert client.post(f"/api/approvals/{approval_id}/approve").status_code == 403
    card = client.get(f"/chat/turns/{task_id}").text
    assert "Waiting for the person who asked" in card and "/approve" not in card

    client.post("/login", data={"user_id": str(people["member"])})
    [pending] = client.get("/api/approvals").json()
    assert pending["arguments"] == EMAIL
    card = client.get(f"/chat/turns/{task_id}").text
    assert "finance@alpha.example" in card and f"/chat/approvals/{approval_id}/approve" in card

    after = client.post(f"/chat/approvals/{approval_id}/approve").text
    assert "typing" in after
    assert client.post(f"/api/approvals/{approval_id}/approve").status_code == 409
