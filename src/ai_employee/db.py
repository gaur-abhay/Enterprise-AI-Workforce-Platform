"""PostgreSQL connection helpers and schema initialisation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from ai_employee.config import get_settings

SCHEMA_PATH = Path(__file__).parent / "ingestion" / "schema.sql"


def dsn() -> str:
    """libpq connection string. Strips the SQLAlchemy driver suffix used in DATABASE_URL."""
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


@contextmanager
def connect(register_types: bool = True) -> Iterator[psycopg.Connection]:
    """Open a connection with the pgvector type adapters registered.

    Pass register_types=False when the vector extension may not exist yet.
    """
    with psycopg.connect(dsn()) as conn:
        if register_types:
            register_vector(conn)
        yield conn


def init_schema() -> None:
    """Apply schema.sql. Safe to run repeatedly.

    The vector width cannot be a query parameter - it is part of the column type - so it is
    substituted from settings. Note that this only affects a table being created: changing
    EMBEDDING_DIM against an existing chunks table needs a migration, not a re-run.
    """
    # A plain replace, not str.format: the DDL contains literal '{}' defaults for the array
    # and jsonb columns, which format() would read as placeholders.
    embedding_dim = int(get_settings().embedding_dim)
    sql = SCHEMA_PATH.read_text(encoding="utf-8").replace("{embedding_dim}", str(embedding_dim))
    with connect(register_types=False) as conn:
        conn.execute(sql)
        conn.commit()
