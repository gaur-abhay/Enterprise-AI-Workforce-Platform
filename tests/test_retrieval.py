"""Retrieval: tenant-scoped, model-scoped, ranked, citation-ready."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from ai_employee.cli.seed import TenantSeed, seed_tenant
from ai_employee.config import get_settings
from ai_employee.context import TurnContext
from ai_employee.db import admin_session
from ai_employee.db.models import Chunk, Document, Employee, SourceConnection
from ai_employee.knowledge import retrieval


def _axis(i: int) -> list[float]:
    vector = [0.0] * get_settings().embedding_dim
    vector[i] = 1.0
    return vector


def _seed(slug: str, passages: list[tuple[str, int, str]]) -> TurnContext:
    """passages: (content, axis, embedding_model)."""
    with admin_session() as session:
        tenant = seed_tenant(session, TenantSeed(slug=slug, name=slug))
        source = session.scalars(
            select(SourceConnection).where(SourceConnection.tenant_id == tenant.id)
        ).one()
        employee = session.scalars(select(Employee).where(Employee.tenant_id == tenant.id)).one()
        document = Document(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            source_connection_id=source.id,
            source_path=f"policies/{slug}.md",
            title=slug,
            mime_type="text/markdown",
            content_hash="0" * 64,
        )
        session.add(document)
        session.flush()
        session.add_all(
            Chunk(
                tenant_id=tenant.id,
                document_id=document.id,
                chunk_index=i,
                content=content,
                char_count=len(content),
                embedding=_axis(axis),
                embedding_model=model,
            )
            for i, (content, axis, model) in enumerate(passages)
        )
    return TurnContext(
        tenant_id=tenant.id,
        employee_id=employee.id,
        actor="system",
        trigger="api",
        correlation_id="test",
    )


@pytest.fixture
def query_axis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retrieval, "embed_query", lambda _: _axis(0))
    monkeypatch.setattr(retrieval, "model_id", lambda: "fake:v1")


def test_returns_closest_own_passages_with_citations(clean_db: None, query_axis: None) -> None:
    alpha = _seed("alpha", [("alpha exact", 0, "fake:v1"), ("alpha far", 1, "fake:v1")])
    _seed("beta", [("beta exact", 0, "fake:v1")])

    hits = retrieval.search(alpha, "anything")

    assert [h.content for h in hits] == ["alpha exact", "alpha far"]
    assert hits[0].score == pytest.approx(1.0)
    assert (hits[0].source, hits[0].uri) == ("alpha.md", "policies/alpha.md")


def test_other_tenant_with_better_matches_is_invisible(clean_db: None, query_axis: None) -> None:
    alpha = _seed("alpha", [("alpha far", 1, "fake:v1")])
    _seed("beta", [(f"beta exact {i}", 0, "fake:v1") for i in range(30)])

    hits = retrieval.search(alpha, "anything", top_k=5)

    assert [h.content for h in hits] == ["alpha far"]


def test_vectors_from_another_model_are_excluded(clean_db: None, query_axis: None) -> None:
    alpha = _seed("alpha", [("current", 1, "fake:v1"), ("stale", 0, "fake:v0")])

    assert [h.content for h in retrieval.search(alpha, "anything")] == ["current"]
