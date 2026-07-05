"""Fixtures and test DB setup.

The `db_pool` and `db_conn` fixtures spin up a dedicated `hable_ya_test`
database on the same Postgres instance that docker-compose exposes. If the
admin DB is unreachable (no compose up, no local Postgres) every dependent
test is skipped with a clear reason — non-DB tests stay green.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest
import pytest_asyncio

from hable_ya.config import settings
from hable_ya.db import close_pool, open_pool, upgrade_to_head

TEST_DB_NAME = "hable_ya_test"


def _replace_path(dsn: str, new_path: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path=new_path))


def _admin_dsn() -> str:
    return _replace_path(settings.database_url, "/postgres")


def _test_dsn() -> str:
    return _replace_path(settings.database_url, f"/{TEST_DB_NAME}")


async def _probe_reachable(dsn: str) -> bool:
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn=dsn), timeout=2.0)
    except (TimeoutError, OSError, asyncpg.PostgresError):
        return False
    await conn.close()
    return True


@contextmanager
def _override_database_url(url: str) -> Iterator[None]:
    original = settings.database_url
    settings.database_url = url
    try:
        yield
    finally:
        settings.database_url = original


async def _drop_and_create_test_db() -> None:
    conn = await asyncpg.connect(dsn=_admin_dsn())
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")
        await conn.execute(f"CREATE DATABASE {TEST_DB_NAME};")
    finally:
        await conn.close()


async def _drop_test_db() -> None:
    conn = await asyncpg.connect(dsn=_admin_dsn())
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE);")
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session")
async def db_pool() -> AsyncIterator[asyncpg.Pool]:
    admin_dsn = _admin_dsn()
    if not await _probe_reachable(admin_dsn):
        pytest.skip(
            f"Postgres not reachable at {admin_dsn}; "
            "run `docker compose up db` to enable DB tests."
        )

    await _drop_and_create_test_db()
    with _override_database_url(_test_dsn()):
        await upgrade_to_head()
        pool = await open_pool()
        try:
            yield pool
        finally:
            await close_pool(pool)
    await _drop_test_db()


@pytest_asyncio.fixture
async def db_conn(db_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    """Transaction-per-test isolation.

    Not suitable for AGE `create_graph` / `drop_graph` (those do DDL with
    side-effects AGE does not reliably roll back) — those tests should acquire
    directly from `db_pool` and clean up explicitly.
    """
    async with db_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn
        finally:
            await tx.rollback()


@pytest_asyncio.fixture
async def clean_learner_state(db_pool: asyncpg.Pool) -> asyncpg.Pool:
    """Truncate learner tables and reset the profile row + AGE graph.

    The learner tests need committed writes (not rollback) so they can call
    the repo across multiple `async with pool.acquire()` blocks and observe
    their own effects. Truncating up front + resetting the seed row is how
    the rollback-free path stays isolated across tests.
    """
    from hable_ya.learner import graph as learner_graph

    async with db_pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE error_observations, error_counts, vocabulary_items, "
            "turns, sessions, band_history RESTART IDENTITY CASCADE"
        )
        await conn.execute(
            "UPDATE learner_profile "
            "SET sessions_completed = 0, "
            "    band = 'A2', "
            "    stable_sessions_at_band = 0, "
            "    last_band_change_at = NULL "
            "WHERE id = 1"
        )
        await conn.execute(
            f"SELECT * FROM cypher('{learner_graph.GRAPH}', $$ "
            f"MATCH (n) DETACH DELETE n $$) AS (v ag_catalog.agtype)"
        )
    return db_pool
