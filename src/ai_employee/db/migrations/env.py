"""Alembic environment. URL from settings unless the caller set sqlalchemy.url."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql.base import ischema_names

from ai_employee.config import get_settings
from ai_employee.db.models import Base

# Lets autogenerate reflect vector columns instead of warning and skipping them.
ischema_names["vector"] = Vector

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
