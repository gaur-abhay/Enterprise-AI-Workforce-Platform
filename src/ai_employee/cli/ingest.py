"""Sync every tenant's source connections, or one tenant's with --tenant."""

from __future__ import annotations

import argparse
import logging
import uuid

from sqlalchemy import select

from ai_employee.db import admin_session
from ai_employee.db.models import SourceConnection, Tenant
from ai_employee.knowledge.pipeline import ingest
from ai_employee.observability import configure_logging

logger = logging.getLogger(__name__)


def _connections(tenant: str | None) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    # Discovery crosses tenants, so it is the one read done outside a tenant session.
    query = select(SourceConnection.tenant_id, SourceConnection.id, Tenant.name).join(Tenant)
    if tenant:
        query = query.where(Tenant.entra_tenant_id == f"seed-{tenant}")
    with admin_session() as session:
        return [(t, s, n) for t, s, n in session.execute(query)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", help="seed slug, e.g. alpha")
    parser.add_argument("--force", action="store_true", help="re-index unchanged documents")
    args = parser.parse_args()

    configure_logging()
    connections = _connections(args.tenant)
    if not connections:
        parser.error("no source connections found; run `make seed` first")
    for tenant_id, source_id, name in connections:
        logger.info("syncing %s source %s", name, source_id)
        ingest(tenant_id, source_id, force=args.force)


if __name__ == "__main__":
    main()
