"""Postgres-backed LangGraph checkpointer, isolated in the `langgraph` schema."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from sqlalchemy import make_url

from ai_employee.config import get_settings

SCHEMA = "langgraph"


def _conninfo() -> str:
    url = make_url(get_settings().database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@contextmanager
def open_checkpointer() -> Iterator[PostgresSaver]:
    """One connection per worker; turns run sequentially on it."""
    with psycopg.connect(
        _conninfo(),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options=f"-c search_path={SCHEMA}",
    ) as conn:
        saver = PostgresSaver(conn)
        saver.setup()
        yield saver
