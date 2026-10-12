"""API: dev login selects the identity, and the identity decides the turn's tenant."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ai_employee.agent import TurnResult
from ai_employee.api import main
from ai_employee.api.routers import turns
from ai_employee.cli.seed import seed
from ai_employee.context import TurnContext
from ai_employee.db import admin_session
from ai_employee.db.models import Tenant, User, UserRole

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
def seen(monkeypatch: pytest.MonkeyPatch) -> list[TurnContext]:
    contexts: list[TurnContext] = []

    def fake_run_turn(ctx: TurnContext, message: str) -> TurnResult:
        contexts.append(ctx)
        return TurnResult(answer=f"echo: {message}", sources=[SOURCE], tool_calls=[])

    monkeypatch.setattr(turns, "run_turn", fake_run_turn)
    return contexts


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


def test_turn_runs_in_the_signed_in_users_tenant(
    client: TestClient, seen: list[TurnContext]
) -> None:
    user_id, tenant_id = _user("beta", UserRole.MEMBER)
    client.post("/login", data={"user_id": str(user_id)})

    response = client.post(
        "/api/turns", json={"message": "hotel cap?"}, headers={"x-request-id": "req-42"}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["answer"], body["request_id"]) == ("echo: hotel cap?", "req-42")
    assert body["sources"][0]["source"] == "policy.md"
    [ctx] = seen
    assert (ctx.tenant_id, ctx.actor, ctx.correlation_id) == (tenant_id, user_id, "req-42")


def test_chat_page_renders_a_turn(client: TestClient, seen: list[TurnContext]) -> None:
    user_id, _ = _user("alpha", UserRole.ADMIN)
    client.post("/login", data={"user_id": str(user_id)})

    assert "Alpha Corp" in client.get("/").text
    fragment = client.post("/chat", data={"message": "<b>hi</b>"}).text
    assert "echo: &lt;b&gt;hi&lt;/b&gt;" in fragment
    assert "policy.md" in fragment


def test_unknown_user_cannot_sign_in(client: TestClient) -> None:
    client.post("/login", data={"user_id": str(uuid.uuid4())})

    assert client.post("/api/turns", json={"message": "hi"}).status_code == 401


def test_logout_clears_identity(client: TestClient, seen: list[TurnContext]) -> None:
    user_id, _ = _user("alpha", UserRole.MEMBER)
    client.post("/login", data={"user_id": str(user_id)})
    client.post("/logout")

    assert client.post("/api/turns", json={"message": "hi"}).status_code == 401


def test_health_reports_each_dependency(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["checks"]["database"] == "ok"
    assert "llm" in body["checks"]
