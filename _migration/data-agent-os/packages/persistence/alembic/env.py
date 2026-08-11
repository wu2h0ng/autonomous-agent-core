"""Alembic migration environment for agent_os_persistence.

Target metadata is the shared SQLAlchemy ``MetaData`` from
``agent_os_persistence.schema``, so ``alembic revision --autogenerate`` stays in
sync with the repositories. The DB URL comes from ``AGENT_OS_DATABASE_URL`` (12-factor)
falling back to ``alembic.ini``.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the package importable when alembic runs from packages/persistence/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_os_persistence.schema import metadata  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_env_url = os.environ.get("AGENT_OS_DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
