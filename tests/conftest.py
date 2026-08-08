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

#: Separate from `TEST_DB_NAME` on purpose (spec #031). The migration-chain tests
#: run `downgrade base`, which drops every learner table and the AGE extension —
#: doing that to the shared session database would pull the schema out from under
#: every test that runs after them.
MIGRATION_DB_NAME = "hable_ya_migration_test"


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


async def _drop_and_create_test_db(name: str = TEST_DB_NAME) -> None:
    conn = await asyncpg.connect(dsn=_admin_dsn())
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE);")
        await conn.execute(f"CREATE DATABASE {name};")
    finally:
        await conn.close()


async def _drop_test_db(name: str = TEST_DB_NAME) -> None:
    conn = await asyncpg.connect(dsn=_admin_dsn())
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE);")
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
async def migration_db() -> AsyncIterator[str]:
    """An empty, unmigrated, throwaway database for the migration-chain tests.

    Yields its DSN with `settings.database_url` pointed at it for the duration —
    which is what redirects alembic, since `env.py` builds `sqlalchemy.url` from
    `settings.async_database_url`, a derived property over `database_url`.

    Deliberately *not* migrated on the way in: these tests drive `upgrade` and
    `downgrade` themselves and need to control the starting revision. Deliberately
    not the session `db_pool` database either — see `MIGRATION_DB_NAME`.

    Function-scoped, so a test that fails mid-chain cannot hand a half-migrated
    database to the next one. That was measured rather than assumed (spec #031
    Open Question 1): the whole file runs in ~1s, because in-process alembic calls
    cost SQL rather than interpreter startup, so isolation is affordable. A shared
    database made a single failure cascade into an unrelated-looking SQL error in
    the following test — the same fragility this fixture exists to keep away from
    the session `db_pool`.
    """
    admin_dsn = _admin_dsn()
    if not await _probe_reachable(admin_dsn):
        pytest.skip(
            f"Postgres not reachable at {admin_dsn}; "
            "run `docker compose up db` to enable DB tests."
        )

    await _drop_and_create_test_db(MIGRATION_DB_NAME)
    dsn = _replace_path(settings.database_url, f"/{MIGRATION_DB_NAME}")
    try:
        with _override_database_url(dsn):
            yield dsn
    finally:
        await _drop_test_db(MIGRATION_DB_NAME)


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

    The statements live in `scripts/learner_reset.py` (spec #030) so this
    fixture and the dev scripts cannot drift apart again — they did, twice: the
    graph clear (#022) and the profile reset. `display_name` is part of that
    shared base state (spec #021), because the PATCH tests commit a name and
    without clearing it the name leaks into every test that runs after them.
    """
    from scripts.learner_reset import reset_learner_state

    async with db_pool.acquire() as conn:
        await reset_learner_state(conn)
    return db_pool
