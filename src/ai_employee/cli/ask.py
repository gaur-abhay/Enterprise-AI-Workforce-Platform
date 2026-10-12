"""Ask a seeded tenant's employee one question, as that tenant's admin."""

from __future__ import annotations

import argparse
import uuid

from sqlalchemy import select

from ai_employee.agent import run_turn
from ai_employee.context import TurnContext
from ai_employee.db import admin_session
from ai_employee.db.models import Employee, Tenant, User, UserRole
from ai_employee.observability import configure_logging


def _context(slug: str) -> TurnContext:
    with admin_session() as session:
        tenant_id, employee_id, user_id = session.execute(
            select(Tenant.id, Employee.id, User.id)
            .join(Employee, Employee.tenant_id == Tenant.id)
            .join(User, User.tenant_id == Tenant.id)
            .where(Tenant.entra_tenant_id == f"seed-{slug}", User.role == UserRole.ADMIN)
        ).one()
    return TurnContext(
        tenant_id=tenant_id,
        employee_id=employee_id,
        actor=user_id,
        trigger="api",
        correlation_id=uuid.uuid4().hex[:12],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--tenant", default="alpha", help="seed slug (default: alpha)")
    args = parser.parse_args()

    configure_logging()
    result = run_turn(_context(args.tenant), args.question)
    print(result.answer)
    for source in result.sources:
        print(f"  [{source['score']:.3f}] {source['uri']} #{source['chunk_index']}")


if __name__ == "__main__":
    main()
