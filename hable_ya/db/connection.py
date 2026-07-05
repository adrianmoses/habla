"""Async Postgres connection pool with Apache AGE bootstrap.

Every new physical connection gets `LOAD 'age'` and a search_path that puts
`ag_catalog` first — so callers can invoke `create_graph(...)` and `cypher(...)`
unqualified without knowing AGE is special.
"""

from __future__ import annotations

import logging

import asyncpg

from hable_ya.config import settings

logger = logging.getLogger(__name__)


async def _init_connection(conn: asyncpg.Connection) -> None:
    # Two separate executes — `LOAD` is a utility statement that some image
    # builds emit a NOTICE on, and mixing it with SET in one multi-statement
    # `execute` has been a sharp edge in practice.
    await conn.execute("LOAD 'age';")
    await conn.execute('SET search_path = ag_catalog, "$user", public;')


async def open_pool() -> asyncpg.Pool:
    logger.info(
        "Opening Postgres pool (min=%d max=%d)",
        settings.db_pool_min_size,
        settings.db_pool_max_size,
    )
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        command_timeout=settings.db_pool_timeout_seconds,
        init=_init_connection,
    )
    if pool is None:
        raise RuntimeError("asyncpg.create_pool returned None")
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()
