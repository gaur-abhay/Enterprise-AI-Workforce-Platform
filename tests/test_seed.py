"""Seed CLI: two tenants, fully provisioned, safe to re-run."""

from __future__ import annotations

from sqlalchemy import func, select

from ai_employee.cli.seed import seed
from ai_employee.db import admin_session, tenant_session
from ai_employee.db.models import Employee, SourceConnection, Tenant, User, UserRole


def test_seed_is_idempotent(clean_db: None) -> None:
    first = seed()
    second = seed()

    assert [t.id for t in first] == [t.id for t in second]
    with admin_session() as session:
        assert session.scalar(select(func.count()).select_from(Tenant)) == 2


def test_each_tenant_is_provisioned(clean_db: None) -> None:
    for tenant in seed():
        with tenant_session(tenant.id) as session:
            roles = sorted(session.scalars(select(User.role)))
            assert roles == [UserRole.ADMIN, UserRole.MEMBER]
            assert session.scalar(select(func.count()).select_from(Employee)) == 1
            assert session.scalar(select(func.count()).select_from(SourceConnection)) == 1
