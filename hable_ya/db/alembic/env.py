"""Alembic async environment.

Uses `hable_ya.config.settings.database_url` as the source of truth and
rewrites it to the SQLAlchemy async form (`postgresql+asyncpg://`). No ORM
models — `target_metadata = None` disables autogenerate; revisions are
hand-authored with `op.execute(...)`.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from hable_ya.config import settings

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers=False` is load-bearing, not tidiness.
    #
    # `fileConfig` defaults to True, which sets `disabled = True` on every
    # logger that already exists and is not named in `alembic.ini` — and this
    # module runs *inside the live app*: `api/main.py`'s lifespan calls
    # `upgrade_to_head()` after the routers have been imported. With the
    # default, every module logger created at import time
    # (`hable_ya.api.session`, `hable_ya.api.external_sessions`,
    # `hable_ya.handoff.callback`, the learner loggers…) is silenced for the
    # rest of the process — a server that has finished booting logs nothing
    # from the code that matters. Found via #033, whose contract requires
    # callback and lifecycle failures to stay diagnosable.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", settings.async_database_url)

# No ORM models → no autogenerate. Revisions are hand-authored.
target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
