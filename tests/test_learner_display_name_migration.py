"""The #021 migration, up and back down.

The suite had no upgrade→downgrade coverage before this — `test_init_db.py` and
`test_db.py` only assert idempotency and that the expected tables exist. A
migration whose `downgrade()` was never run is a claim, not a fact, so this
exercises it against the real database.

It runs on the session-scoped `db_pool`, whose fixture keeps
`settings.database_url` pointed at `hable_ya_test` for the whole session, and it
restores head before returning so the tests that follow see the schema they
expect.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config

REVISION = "f1e6a742b90c"
_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _config() -> Config:
    return Config(str(_ALEMBIC_INI))


async def _run(fn: object, *args: str) -> None:
    # Alembic's env.py calls `asyncio.run` internally, so it cannot run on a
    # thread that already owns a loop — same reason `upgrade_to_head` does this.
    await asyncio.to_thread(fn, _config(), *args)  # type: ignore[arg-type]


async def _has_display_name(pool: asyncpg.Pool) -> bool:
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'learner_profile'
                      AND column_name = 'display_name'
                )
                """
            )
        )


async def test_display_name_upgrade_downgrade_round_trip(
    db_pool: asyncpg.Pool,
) -> None:
    assert await _has_display_name(db_pool) is True

    try:
        await _run(command.downgrade, "-1")
        assert await _has_display_name(db_pool) is False
    finally:
        # Restore head even if the assertion above fails — a half-migrated
        # database would fail every test that runs after this one.
        await _run(command.upgrade, "head")

    assert await _has_display_name(db_pool) is True


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
