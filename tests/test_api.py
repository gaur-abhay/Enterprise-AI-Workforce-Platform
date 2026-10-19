"""API: dev login selects the identity, and the identity decides the turn's tenant."""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ai_employee.agent import TurnResult
from ai_employee.api import main
from ai_employee.cli.seed import seed
from ai_employee.context import TurnContext
from ai_employee.db import admin_session
from ai_employee.db.models import Tenant, User, UserRole
from ai_employee.execution.worker import Worker

SOURCE = {
    "chunk_id": "c1",
    "document_id": "d1",
    "source": "policy.md",
    "title": "policy",
    "uri": "policy.md",
    "page": None,
    "chunk_index": 0,
    "indexed_at": "2026-10-12T00:00:00+00:00",
    "score": 0.9,
    "content": "Hotels capped at 250 EUR.",
}


@pytest.fixture
def seen() -> list[TurnContext]:
    return []


def _work(seen: list[TurnContext]) -> None:
    def fake_run_turn(ctx: TurnContext, message: str, **_: object) -> TurnResult:
        seen.append(ctx)
        return TurnResult(answer=f"echo: {message}", sources=[SOURCE], tool_calls=[])

    assert Worker(run=fake_run_turn).run_once(None)


@pytest.fixture
def client(clean_db: None) -> TestClient:
    seed()
    return TestClient(main.app)


def _user(tenant_slug: str, role: UserRole) -> tuple[uuid.UUID, uuid.UUID]:
    with admin_session() as session:
        user_id, tenant_id = session.execute(
            select(User.id, Tenant.id)
            .join(Tenant)
            .where(Tenant.entra_tenant_id == f"seed-{tenant_slug}", User.role == role)
        ).one()
    return user_id, tenant_id


def test_unauthenticated_requests_are_refused(client: TestClient) -> None:
    assert client.post("/api/turns", json={"message": "hi"}).status_code == 401
    page = client.get("/", follow_redirects=False)
    assert (page.status_code, page.headers["location"]) == (303, "/login")


def test_login_page_lists_seeded_users(client: TestClient) -> None:
    body = client.get("/login").text
    assert "Alpha Corp" in body and "Beta Ltd" in body


def test_turn_is_accepted_then_answered_in_the_users_tenant(
    client: TestClient, seen: list[TurnContext]
) -> None:
    user_id, tenant_id = _user("beta", UserRole.MEMBER)
    client.post("/login", data={"user_id": str(user_id)})

    accepted = client.post(
        "/api/turns", json={"message": "hotel cap?"}, headers={"x-request-id": "req-42"}
    )
    assert accepted.status_code == 202
    task_id = accepted.json()["task_id"]
    assert client.get(f"/api/turns/{task_id}").json()["status"] == "queued"

    _work(seen)

    body = client.get(f"/api/turns/{task_id}").json()
    assert (body["status"], body["request_id"]) == ("succeeded", "req-42")
    assert body["result"]["answer"] == "echo: hotel cap?"
    assert body["result"]["sources"][0]["source"] == "policy.md"
    [ctx] = seen
    assert (ctx.tenant_id, ctx.actor, ctx.correlation_id) == (tenant_id, user_id, "req-42")


def test_another_tenants_turn_is_not_found(client: TestClient) -> None:
    alpha_user, _ = _user("alpha", UserRole.MEMBER)
    beta_user, _ = _user("beta", UserRole.MEMBER)
    client.post("/login", data={"user_id": str(beta_user)})
    task_id = client.post("/api/turns", json={"message": "secret"}).json()["task_id"]

    client.post("/login", data={"user_id": str(alpha_user)})

    assert client.get(f"/api/turns/{task_id}").status_code == 404


def test_chat_page_polls_until_the_turn_is_done(
    client: TestClient, seen: list[TurnContext]
) -> None:
    user_id, _ = _user("alpha", UserRole.ADMIN)
    client.post("/login", data={"user_id": str(user_id)})

    assert "Alpha Corp" in client.get("/").text
    pending = client.post("/chat", data={"message": "<b>hi</b>"}).text
    assert "&lt;b&gt;hi&lt;/b&gt;" in pending
    [poll_url] = re.findall(r'hx-get="(/chat/turns/[^"]+)"', pending)

    _work(seen)

    reply = client.get(poll_url).text
    assert "echo: &lt;b&gt;hi&lt;/b&gt;" in reply and "policy.md" in reply
    assert "hx-get" not in reply


def test_unknown_user_cannot_sign_in(client: TestClient) -> None:
    client.post("/login", data={"user_id": str(uuid.uuid4())})

    assert client.post("/api/turns", json={"message": "hi"}).status_code == 401


def test_logout_clears_identity(client: TestClient) -> None:
    user_id, _ = _user("alpha", UserRole.MEMBER)
    client.post("/login", data={"user_id": str(user_id)})
    client.post("/logout")

    assert client.post("/api/turns", json={"message": "hi"}).status_code == 401


def test_health_reports_each_dependency(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["checks"]["database"] == "ok"
    assert "llm" in body["checks"]
