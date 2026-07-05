"""Stage 0 spike for spec 029 — validate AGE MERGE + edge patterns.

This file is throwaway. It exercises the cypher-through-asyncpg patterns
`hable_ya/learner/graph.py` will depend on, before that module is written.
Findings are recorded inline so future archaeology does not have to rerun
the spike. Deletes/consolidates into `tests/test_learner_graph.py` at
spec-029 merge time.

Runs against a short-lived `spec029_spike_graph` graph created + dropped
per test (using the spec-028 `drop_graph('name'::name, true)` convention).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

GRAPH = "spec029_spike_graph"


async def _drop_graph_if_exists(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"SELECT drop_graph('{GRAPH}'::name, true) "
        f"WHERE EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = '{GRAPH}')"
    )


async def _graph_exists(conn: asyncpg.Connection) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = $1)",
            GRAPH,
        )
    )


@pytest_asyncio.fixture
async def spike_graph(db_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    async with db_pool.acquire() as conn:
        await _drop_graph_if_exists(conn)
        await conn.execute(f"SELECT create_graph('{GRAPH}')")
    try:
        yield db_pool
    finally:
        async with db_pool.acquire() as conn:
            await _drop_graph_if_exists(conn)


async def test_graph_creation_is_not_idempotent(db_pool: asyncpg.Pool) -> None:
    """Finding: `create_graph(name)` errors if the graph already exists.

    AGE 1.7 does not expose a `CREATE GRAPH IF NOT EXISTS`-style form; the
    idempotent path is to check `ag_catalog.ag_graph` yourself and only call
    `create_graph` when the row is missing. The spec-029 migration uses this
    guard rather than swallowing an exception.
    """
    async with db_pool.acquire() as conn:
        await _drop_graph_if_exists(conn)
        await conn.execute(f"SELECT create_graph('{GRAPH}')")
        try:
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(f"SELECT create_graph('{GRAPH}')")
        finally:
            await _drop_graph_if_exists(conn)


async def test_single_node_merge_is_idempotent(
    spike_graph: asyncpg.Pool,
) -> None:
    async with spike_graph.acquire() as conn:
        for _ in range(2):
            await conn.execute(
                f"""
                SELECT * FROM cypher('{GRAPH}', $$
                    MERGE (l:Learner {{id: 1}})
                $$) AS (v ag_catalog.agtype)
                """
            )
        row = await conn.fetchrow(
            f"""
            SELECT * FROM cypher('{GRAPH}', $$
                MATCH (l:Learner) RETURN count(l)
            $$) AS (c ag_catalog.agtype)
            """
        )
        assert row is not None
        # agtype renders integers as bare numerals; str() round-trips.
        assert str(row["c"]) == "1"


async def test_property_update_via_merge_coalesce(
    spike_graph: asyncpg.Pool,
) -> None:
    """Finding: AGE does NOT support `ON CREATE SET` / `ON MATCH SET` on MERGE.

    The openCypher / Neo4j idiom fails with "syntax error at or near 'ON'".
    The working pattern is `MERGE (...) SET x = coalesce(x, 0) + 1` — the SET
    runs for both the create and match branches, and coalesce handles the
    initial NULL. Production graph writer uses this form for counter upserts.
    """
    async with spike_graph.acquire() as conn:
        for _ in range(3):
            await conn.execute(
                f"""
                SELECT * FROM cypher('{GRAPH}', $$
                    MERGE (v:VocabItem {{lemma: 'comer'}})
                    SET v.production_count = coalesce(v.production_count, 0) + 1
                $$) AS (v ag_catalog.agtype)
                """
            )
        row = await conn.fetchrow(
            f"""
            SELECT * FROM cypher('{GRAPH}', $$
                MATCH (v:VocabItem {{lemma: 'comer'}}) RETURN v.production_count
            $$) AS (c ag_catalog.agtype)
            """
        )
        assert row is not None
        assert str(row["c"]) == "3"


async def test_edge_merge_updates_property_without_duplication(
    spike_graph: asyncpg.Pool,
) -> None:
    async with spike_graph.acquire() as conn:
        # Seed learner + vocab nodes.
        await conn.execute(
            f"""
            SELECT * FROM cypher('{GRAPH}', $$
                MERGE (l:Learner {{id: 1}})
                MERGE (v:VocabItem {{lemma: 'comer'}})
            $$) AS (v ag_catalog.agtype)
            """
        )
        for at in ("2026-04-22T00:00:00Z", "2026-04-22T01:00:00Z"):
            await conn.execute(
                f"""
                SELECT * FROM cypher('{GRAPH}', $$
                    MATCH (l:Learner {{id: 1}}), (v:VocabItem {{lemma: 'comer'}})
                    MERGE (l)-[r:PRODUCED]->(v)
                    SET r.last_at = '{at}'
                $$) AS (v ag_catalog.agtype)
                """
            )
        row = await conn.fetchrow(
            f"""
            SELECT * FROM cypher('{GRAPH}', $$
                MATCH (:Learner)-[r:PRODUCED]->(:VocabItem)
                RETURN count(r), max(r.last_at)
            $$) AS (c ag_catalog.agtype, last_at ag_catalog.agtype)
            """
        )
        assert row is not None
        assert str(row["c"]) == "1"
        assert "2026-04-22T01:00:00Z" in str(row["last_at"])


async def test_string_literals_accents_and_whitespace(
    spike_graph: asyncpg.Pool,
) -> None:
    """Finding: double-dollar-quoted cypher handles accents + whitespace fine.

    Single quotes inside values break the literal ($$ delimits the cypher
    block, single quotes delimit strings). The production graph writer
    rejects non-word lemmas/categories before they reach cypher rather than
    attempting SQL-style escaping.
    """
    async with spike_graph.acquire() as conn:
        for lemma in ("café", "por favor"):
            await conn.execute(
                f"""
                SELECT * FROM cypher('{GRAPH}', $$
                    MERGE (v:VocabItem {{lemma: '{lemma}'}})
                $$) AS (v ag_catalog.agtype)
                """
            )
        row = await conn.fetchrow(
            f"""
            SELECT * FROM cypher('{GRAPH}', $$
                MATCH (v:VocabItem) RETURN count(v)
            $$) AS (c ag_catalog.agtype)
            """
        )
        assert row is not None
        assert str(row["c"]) == "2"


async def test_transaction_rollback_undoes_merge(
    spike_graph: asyncpg.Pool,
) -> None:
    async with spike_graph.acquire() as conn:
        with pytest.raises(RuntimeError):
            async with conn.transaction():
                await conn.execute(
                    f"""
                    SELECT * FROM cypher('{GRAPH}', $$
                        MERGE (v:VocabItem {{lemma: 'transient'}})
                    $$) AS (v ag_catalog.agtype)
                    """
                )
                raise RuntimeError("force rollback")
        row = await conn.fetchrow(
            f"""
            SELECT * FROM cypher('{GRAPH}', $$
                MATCH (v:VocabItem {{lemma: 'transient'}}) RETURN count(v)
            $$) AS (c ag_catalog.agtype)
            """
        )
        assert row is not None
        assert str(row["c"]) == "0"
