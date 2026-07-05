"""Integration tests for the Postgres + Apache AGE plumbing.

Requires a reachable Postgres (compose `db` service). If unreachable, the
`db_pool` session fixture skips every test in this module with a clear
reason — see tests/conftest.py.
"""

from __future__ import annotations

import asyncpg


async def test_pool_lifecycle(db_pool: asyncpg.Pool) -> None:
    async with db_pool.acquire() as conn:
        value = await conn.fetchval("SELECT 1")
        assert value == 1


async def test_age_loaded_on_acquire(db_conn: asyncpg.Connection) -> None:
    search_path = await db_conn.fetchval("SHOW search_path")
    assert "ag_catalog" in search_path
    graph_count = await db_conn.fetchval("SELECT COUNT(*) FROM ag_catalog.ag_graph")
    assert graph_count >= 0


async def test_age_extension_present(db_conn: asyncpg.Connection) -> None:
    row = await db_conn.fetchrow(
        "SELECT extname FROM pg_extension WHERE extname = 'age'"
    )
    assert row is not None
    assert row["extname"] == "age"


async def test_upgrade_to_head_idempotent(db_conn: asyncpg.Connection) -> None:
    from hable_ya.db import upgrade_to_head

    before = await db_conn.fetchval("SELECT version_num FROM alembic_version")
    await upgrade_to_head()
    after = await db_conn.fetchval("SELECT version_num FROM alembic_version")
    assert before == after


async def test_learner_schema_tables_exist(db_conn: asyncpg.Connection) -> None:
    expected = {
        "learner_profile",
        "sessions",
        "turns",
        "error_observations",
        "error_counts",
        "vocabulary_items",
    }
    rows = await db_conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    present = {r["tablename"] for r in rows}
    assert expected <= present, f"missing tables: {expected - present}"


async def test_learner_profile_seed_row(db_conn: asyncpg.Connection) -> None:
    row = await db_conn.fetchrow(
        "SELECT id, band, sessions_completed FROM learner_profile WHERE id = 1"
    )
    assert row is not None
    assert row["id"] == 1
    assert row["band"] == "A2"
    assert row["sessions_completed"] == 0


async def test_learner_knowledge_graph_exists(db_conn: asyncpg.Connection) -> None:
    row = await db_conn.fetchrow(
        "SELECT name FROM ag_catalog.ag_graph WHERE name = 'learner_knowledge'"
    )
    assert row is not None


async def test_age_smoke_create_graph_and_cypher(db_pool: asyncpg.Pool) -> None:
    graph = "smoke_test_graph"
    async with db_pool.acquire() as conn:
        try:
            await conn.execute(f"SELECT create_graph('{graph}')")
            await conn.execute(
                f"""
                SELECT * FROM cypher('{graph}', $$
                    CREATE (:Marker {{name: 'x'}})
                $$) AS (v ag_catalog.agtype)
                """
            )
            row = await conn.fetchrow(
                f"""
                SELECT * FROM cypher('{graph}', $$
                    MATCH (n:Marker) RETURN n.name
                $$) AS (name ag_catalog.agtype)
                """
            )
            assert row is not None
            assert "x" in str(row["name"])
        finally:
            # Cast the graph name to `name`: asyncpg sends literals as
            # `unknown` via the extended-query path, and drop_graph's
            # overload resolution fails on (unknown, boolean).
            await conn.execute(f"SELECT drop_graph('{graph}'::name, true)")
