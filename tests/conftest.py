"""Test-wide setup.

DATABASE_URL has no default in Settings, so it has to exist before anything imports
ai_employee.config. Setting it here — conftest is imported before any test module — keeps
every test independent of the developer's .env and of CI having a database at all.

Database tests run against TEST_DATABASE_URL (environment or .env), which is dropped and
recreated per session. Without it they are skipped.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
# Settings falls back to .env when a variable is unset, which would otherwise leak a
# developer's real providers and keys into assertions about defaults.
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("EMBEDDING_PROVIDER", "gemini")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import make_url, text

from ai_employee.config import get_settings
from ai_employee.db import admin_session, get_engine
from ai_employee.db.session import _session_factory


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Settings are cached per process, so a test that edits the environment would otherwise
    be seen — or not — depending on which test ran first."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or dotenv_values(".env").get("TEST_DATABASE_URL")


def _recreate_database(url: str) -> None:
    parsed = make_url(url)
    # The database is dropped; refuse anything not plainly a test database.
    if not (parsed.database or "").endswith("_test"):
        raise RuntimeError(f"TEST_DATABASE_URL must name a *_test database, got {parsed.database}")
    maintenance = parsed.set(drivername="postgresql", database="postgres")
    conninfo = maintenance.render_as_string(hide_password=False)
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{parsed.database}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{parsed.database}"')


@pytest.fixture(scope="session")
def database() -> Iterator[str]:
    """A freshly migrated database; DATABASE_URL points at it for the session."""
    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    _recreate_database(url)

    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    get_engine.cache_clear()
    _session_factory.cache_clear()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    yield url

    get_engine().dispose()
    get_engine.cache_clear()
    _session_factory.cache_clear()
    os.environ["DATABASE_URL"] = previous


@pytest.fixture
def clean_db(database: str) -> Iterator[None]:
    yield
    with admin_session() as session:
        # DELETE cascades through the foreign keys; cheaper than TRUNCATE for a few rows.
        session.execute(text("DELETE FROM tenants"))
