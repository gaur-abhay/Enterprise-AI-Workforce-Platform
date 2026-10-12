"""Who is calling. The only module that reads identity from a request.

The dev stub trusts a user id stored in the signed session cookie; Entra SSO replaces
`DevLogin` without changing `Identity` or anything that depends on it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from ai_employee.context import Trigger, TurnContext
from ai_employee.db import admin_session
from ai_employee.db.models import Employee, Tenant, User, UserRole

SESSION_USER_KEY = "user_id"


@dataclass(frozen=True)
class Identity:
    tenant_id: uuid.UUID
    tenant_name: str
    employee_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    role: UserRole

    def turn_context(self, correlation_id: str, trigger: Trigger = "api") -> TurnContext:
        return TurnContext(
            tenant_id=self.tenant_id,
            employee_id=self.employee_id,
            actor=self.user_id,
            trigger=trigger,
            correlation_id=correlation_id,
        )


def _load(user_id: uuid.UUID) -> Identity | None:
    # Runs before the tenant is known, so it is the one request-path read outside RLS.
    with admin_session() as session:
        row = session.execute(
            select(User, Tenant.name, Employee.id)
            .join(Tenant, Tenant.id == User.tenant_id)
            .join(Employee, Employee.tenant_id == User.tenant_id)
            .where(User.id == user_id)
        ).one_or_none()
    if row is None:
        return None
    user, tenant_name, employee_id = row
    return Identity(
        tenant_id=user.tenant_id,
        tenant_name=tenant_name,
        employee_id=employee_id,
        user_id=user.id,
        display_name=user.display_name,
        role=user.role,
    )


class DevLogin:
    """Stub provider: pick any seeded user."""

    @staticmethod
    def users() -> list[tuple[uuid.UUID, str, str, UserRole]]:
        with admin_session() as session:
            rows = session.execute(
                select(User.id, Tenant.name, User.display_name, User.role)
                .join(Tenant, Tenant.id == User.tenant_id)
                .order_by(Tenant.name, User.role)
            )
            return [(r[0], r[1], r[2], r[3]) for r in rows]

    @staticmethod
    def sign_in(request: Request, user_id: uuid.UUID) -> bool:
        if _load(user_id) is None:
            return False
        request.session[SESSION_USER_KEY] = str(user_id)
        return True

    @staticmethod
    def sign_out(request: Request) -> None:
        request.session.clear()


def optional_identity(request: Request) -> Identity | None:
    raw = request.session.get(SESSION_USER_KEY)
    try:
        return _load(uuid.UUID(raw)) if raw else None
    except ValueError:
        return None


def current_identity(request: Request) -> Identity:
    identity = optional_identity(request)
    if identity is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in required")
    return identity
