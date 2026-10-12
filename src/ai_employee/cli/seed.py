"""Seed demo tenants, their users, employee and directory source. Idempotent."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_employee.db import admin_session
from ai_employee.db.models import (
    Employee,
    SourceConnection,
    SourceKind,
    Tenant,
    TenantStatus,
    User,
    UserRole,
)
from ai_employee.observability import configure_logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantSeed:
    slug: str
    name: str

    @property
    def entra_tenant_id(self) -> str:
        # Stands in for the Entra `tid` until real sign-in exists; also the upsert key.
        return f"seed-{self.slug}"

    @property
    def corpus_path(self) -> str:
        return f"data/tenants/{self.slug}"


DEFAULT_TENANTS = (
    TenantSeed(slug="alpha", name="Alpha Corp"),
    TenantSeed(slug="beta", name="Beta Ltd"),
)


def seed_tenant(session: Session, spec: TenantSeed) -> Tenant:
    existing = session.scalar(select(Tenant).where(Tenant.entra_tenant_id == spec.entra_tenant_id))
    if existing is not None:
        return existing

    # Seeded tenants skip consent and source setup, so they start configured.
    tenant = Tenant(
        id=uuid.uuid4(),
        name=spec.name,
        entra_tenant_id=spec.entra_tenant_id,
        status=TenantStatus.CONFIGURED,
    )
    session.add(tenant)
    session.flush()

    admin = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"admin@{spec.slug}.example",
        display_name=f"{spec.name} Admin",
        role=UserRole.ADMIN,
    )
    member = User(
        tenant_id=tenant.id,
        email=f"member@{spec.slug}.example",
        display_name=f"{spec.name} Member",
        role=UserRole.MEMBER,
    )
    session.add_all([admin, member, Employee(tenant_id=tenant.id, name="Coworker")])
    session.flush()
    session.add(
        SourceConnection(
            tenant_id=tenant.id,
            name="documents",
            kind=SourceKind.DIRECTORY,
            config={"path": spec.corpus_path},
            created_by=admin.id,
        )
    )
    session.flush()
    return tenant


def seed(specs: tuple[TenantSeed, ...] = DEFAULT_TENANTS) -> list[Tenant]:
    with admin_session() as session:
        return [seed_tenant(session, spec) for spec in specs]


def main() -> None:
    configure_logging()
    for tenant in seed():
        logger.info("tenant %s %s (%s)", tenant.name, tenant.id, tenant.status)


if __name__ == "__main__":
    main()
