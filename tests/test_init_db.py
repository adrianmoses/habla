"""Smoke test for scripts/init_db.py's idempotency guarantee."""

from __future__ import annotations

import asyncpg

from hable_ya.db import upgrade_to_head


async def test_upgrade_to_head_twice_is_noop(db_pool: asyncpg.Pool) -> None:
    # db_pool fixture has already run upgrade once; calling again should be
    # a no-op and not raise.
    async with db_pool.acquire() as conn:
        first = await conn.fetchval("SELECT version_num FROM alembic_version")
        count_before = await conn.fetchval("SELECT COUNT(*) FROM alembic_version")
    await upgrade_to_head()
    async with db_pool.acquire() as conn:
        second = await conn.fetchval("SELECT version_num FROM alembic_version")
        count_after = await conn.fetchval("SELECT COUNT(*) FROM alembic_version")
    assert first == second
    assert count_before == count_after == 1
