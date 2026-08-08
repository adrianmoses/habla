"""What the #021 migration produced: a nullable, unbackfilled `display_name`.

The round-trip that used to live here moved to `tests/test_migration_chain.py`
(spec #031), which covers **every** revision rather than this one, and does it on
a throwaway database. This file kept the assertions that are about the shape of
the column rather than the reversibility of the migration.

That move was not only for coverage. The old test downgraded the *shared*
session database and restored head in a `finally`, so any failure between the two
left every subsequent test running against a half-migrated schema — one failure
presenting as a cascade of unrelated ones.
"""

from __future__ import annotations

import asyncpg


async def test_display_name_is_nullable_with_no_default(
    db_pool: asyncpg.Pool,
) -> None:
    # Nullable and unbackfilled is the whole point: the existing row's name is
    # genuinely unset, and NULL is how that stays sayable.
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT is_nullable, column_default, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'learner_profile'
              AND column_name = 'display_name'
            """
        )
    assert row is not None
    assert row["is_nullable"] == "YES"
    assert row["column_default"] is None
    assert row["data_type"] == "text"


async def test_singleton_constraint_survives_the_migration(
    db_pool: asyncpg.Pool,
) -> None:
    async with db_pool.acquire() as conn:
        constraint = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public'
              AND t.relname = 'learner_profile'
              AND c.contype = 'c'
            """
        )
    assert constraint is not None
    assert "id = 1" in str(constraint)
