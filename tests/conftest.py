"""Test-wide setup.

DATABASE_URL has no default in Settings, so it has to exist before anything imports
ai_employee.config. Setting it here — conftest is imported before any test module — keeps
every test independent of the developer's .env and of CI having a database at all.
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

import pytest

from ai_employee.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Settings are cached per process, so a test that edits the environment would otherwise
    be seen — or not — depending on which test ran first."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
