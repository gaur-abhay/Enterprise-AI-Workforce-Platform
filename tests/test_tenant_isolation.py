"""Seam 4: tenants cannot see or touch each other's rows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from ai_employee.config import get_settings
from ai_employee.db import admin_session, get_engine, tenant_session
from ai_employee.db.models import (
    Base,
    Chunk,
    Document,
    Employee,
    SourceConnection,
    SourceKind,
    Tenant,
    User,
    UserRole,
)


@dataclass
class Seeded:
    tenant_id: uuid.UUID
    document_id: uuid.UUID


def _seed_tenant(name: str) -> Seeded:
    tenant = Tenant(id=uuid.uuid4(), name=name)
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"admin@{name}.test",
        display_name="Admin",
        role=UserRole.ADMIN,
    )
    source = SourceConnection(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="docs",
        kind=SourceKind.DIRECTORY,
        config={"path": f"data/{name}"},
        created_by=user.id,
    )
    document = Document(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        source_connection_id=source.id,
        source_path=f"{name}/policy.md",
        title=f"{name} policy",
        mime_type="text/markdown",
        content_hash="0" * 64,
    )
    chunk = Chunk(
        tenant_id=tenant.id,
        document_id=document.id,
        chunk_index=0,
        content=f"{name} refund policy",
        char_count=20,
        embedding=[0.1] * get_settings().embedding_dim,
        embedding_model="test",
    )
    employee = Employee(tenant_id=tenant.id, name="Coworker")
    with admin_session() as session:
        session.add(tenant)
        session.flush()
        session.add_all([user, employee])
        session.flush()
        session.add(source)
        session.flush()
        session.add(document)
        session.flush()
        session.add(chunk)
    return Seeded(tenant_id=tenant.id, document_id=document.id)


@pytest.fixture
def tenants(clean_db: None) -> tuple[Seeded, Seeded]:
    return _seed_tenant("alpha"), _seed_tenant("beta")


@pytest.mark.parametrize("model", [Tenant, User, Employee, SourceConnection, Document, Chunk])
def test_tenant_sees_only_its_own_rows(tenants: tuple[Seeded, Seeded], model: type[Base]) -> None:
    alpha, _ = tenants
    column = model.id if model is Tenant else model.tenant_id  # type: ignore[attr-defined]
    with tenant_session(alpha.tenant_id) as session:
        owners = set(session.scalars(select(column)))
    assert owners == {alpha.tenant_id}


def test_unbound_session_sees_nothing(tenants: tuple[Seeded, Seeded]) -> None:
    role = get_settings().db_app_role
    with admin_session() as session:
        session.execute(text(f'SET LOCAL ROLE "{role}"'))
        assert session.scalar(select(func.count()).select_from(Document)) == 0


def test_cannot_insert_into_another_tenant(tenants: tuple[Seeded, Seeded]) -> None:
    alpha, beta = tenants
    with (
        pytest.raises(DBAPIError, match="row-level security"),
        tenant_session(alpha.tenant_id) as session,
    ):
        session.add(Employee(tenant_id=beta.tenant_id, name="Intruder"))
        session.flush()


def test_cannot_modify_another_tenants_rows(tenants: tuple[Seeded, Seeded]) -> None:
    alpha, beta = tenants
    with tenant_session(alpha.tenant_id) as session:
        result = session.execute(
            update(Document).where(Document.id == beta.document_id).values(title="hijacked")
        )
        assert result.rowcount == 0  # type: ignore[attr-defined]
    with admin_session() as session:
        assert session.get(Document, beta.document_id).title == "beta policy"  # type: ignore[union-attr]


def test_chunk_cannot_reference_another_tenants_document(tenants: tuple[Seeded, Seeded]) -> None:
    alpha, beta = tenants
    with pytest.raises(IntegrityError), admin_session() as session:
        session.add(
            Chunk(
                tenant_id=alpha.tenant_id,
                document_id=beta.document_id,
                chunk_index=1,
                content="cross-tenant",
                char_count=12,
                embedding=[0.1] * get_settings().embedding_dim,
                embedding_model="test",
            )
        )
        session.flush()


def test_migrations_match_models(database: str) -> None:
    with get_engine().connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []
