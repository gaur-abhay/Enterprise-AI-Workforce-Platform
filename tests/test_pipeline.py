"""Ingestion against a real database with a fake embedder."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from ai_employee.cli.seed import TenantSeed, seed_tenant
from ai_employee.config import get_settings
from ai_employee.db import admin_session, tenant_session
from ai_employee.db.models import Chunk, Document, SourceConnection, Tenant, TenantStatus
from ai_employee.knowledge import pipeline


class FakeEmbedder:
    def __init__(self) -> None:
        self.model = "fake:v1"
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[1.0] + [0.0] * (get_settings().embedding_dim - 1) for _ in texts]


@pytest.fixture
def embedder(monkeypatch: pytest.MonkeyPatch) -> FakeEmbedder:
    fake = FakeEmbedder()
    monkeypatch.setattr(pipeline, "embed_documents", fake.embed_documents)
    monkeypatch.setattr(pipeline, "model_id", lambda: fake.model)
    return fake


@pytest.fixture
def corpus(tmp_path: Path, clean_db: None) -> tuple[uuid.UUID, uuid.UUID, Path]:
    (tmp_path / "refunds.md").write_text("# Refunds\n\n" + "Refunds take 14 days. " * 20)
    (tmp_path / "travel.txt").write_text("Economy class for flights under six hours. " * 10)
    with admin_session() as session:
        tenant = seed_tenant(session, TenantSeed(slug="alpha", name="Alpha"))
        source = session.scalars(select(SourceConnection)).one()
        source.config = {"path": str(tmp_path)}
    return tenant.id, source.id, tmp_path


def _statuses(results: list[pipeline.IngestResult]) -> dict[str, str]:
    return {r.uri: r.status for r in results}


def _bump_mtime(path: Path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_indexes_into_the_tenant_and_activates_it(corpus, embedder) -> None:  # type: ignore[no-untyped-def]
    tenant_id, source_id, _ = corpus

    results = pipeline.ingest(tenant_id, source_id)

    assert _statuses(results) == {"refunds.md": "indexed", "travel.txt": "indexed"}
    with tenant_session(tenant_id) as session:
        chunks = session.scalars(select(Chunk)).all()
        assert chunks and {c.tenant_id for c in chunks} == {tenant_id}
        assert session.get_one(Tenant, tenant_id).status is TenantStatus.ACTIVE
        assert session.get_one(SourceConnection, source_id).last_synced_at is not None


def test_unchanged_documents_are_not_reread(corpus, embedder) -> None:  # type: ignore[no-untyped-def]
    tenant_id, source_id, _ = corpus
    pipeline.ingest(tenant_id, source_id)
    calls = embedder.calls

    results = pipeline.ingest(tenant_id, source_id)

    assert set(_statuses(results).values()) == {"skipped"}
    assert embedder.calls == calls


def test_touched_file_updates_its_token_without_reembedding(corpus, embedder) -> None:  # type: ignore[no-untyped-def]
    tenant_id, source_id, root = corpus
    pipeline.ingest(tenant_id, source_id)
    calls = embedder.calls
    _bump_mtime(root / "refunds.md")

    first = pipeline.ingest(tenant_id, source_id)
    second = pipeline.ingest(tenant_id, source_id)

    assert [r.detail for r in first if r.uri == "refunds.md"] == ["content unchanged"]
    assert [r.detail for r in second if r.uri == "refunds.md"] == ["unchanged at source"]
    assert embedder.calls == calls


def test_embedding_model_change_forces_reindex(corpus, embedder) -> None:  # type: ignore[no-untyped-def]
    tenant_id, source_id, _ = corpus
    pipeline.ingest(tenant_id, source_id)
    embedder.model = "fake:v2"

    results = pipeline.ingest(tenant_id, source_id)

    assert set(_statuses(results).values()) == {"indexed"}


def test_deleted_file_is_pruned(corpus, embedder) -> None:  # type: ignore[no-untyped-def]
    tenant_id, source_id, root = corpus
    pipeline.ingest(tenant_id, source_id)
    (root / "travel.txt").unlink()

    results = pipeline.ingest(tenant_id, source_id)

    assert _statuses(results)["travel.txt"] == "pruned"
    with tenant_session(tenant_id) as session:
        assert session.scalars(select(Document.source_path)).all() == ["refunds.md"]
