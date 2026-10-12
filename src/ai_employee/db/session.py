"""Engine and sessions. The only place tenant binding for RLS happens.

A tenant session switches to the unprivileged application role and sets `app.tenant_id`,
both transaction-local, so a pooled connection never carries either past the transaction.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ai_employee.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def tenant_session(tenant_id: UUID) -> Iterator[Session]:
    """One transaction, restricted by RLS to `tenant_id`. Commits on success."""
    # The role name is interpolated, not bound: SET ROLE does not accept parameters.
    role = get_settings().db_app_role
    with _session_factory().begin() as session:
        session.execute(text(f'SET LOCAL ROLE "{role}"'))
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        yield session


@contextmanager
def admin_session() -> Iterator[Session]:
    """One transaction as the connecting role, for seeding and operations only.

    Bypasses RLS only if that role is a superuser or has BYPASSRLS.
    """
    with _session_factory().begin() as session:
        yield session
