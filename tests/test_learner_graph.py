"""Graph writer upserts against the `learner_knowledge` AGE graph."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest_asyncio

from hable_ya.learner import graph


@pytest_asyncio.fixture
async def clean_graph(db_pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Pool]:
    # Per conftest.py:101-105, AGE graph DDL can't use the rollback-per-test
    # `db_conn` fixture. Strip the graph contents before each test.
    async with db_pool.acquire() as conn:
        await conn.execute(
            f"SELECT * FROM cypher('{graph.GRAPH}', $$ "
            f"MATCH (n) DETACH DELETE n $$) AS (v ag_catalog.agtype)"
        )
    yield db_pool


async def _count(pool: asyncpg.Pool, cypher_body: str) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT * FROM cypher('{graph.GRAPH}', $$ {cypher_body} $$) "
            f"AS (c ag_catalog.agtype)"
        )
    assert row is not None
    return int(str(row["c"]))


async def test_ensure_learner_node_is_idempotent(
    clean_graph: asyncpg.Pool,
) -> None:
    async with clean_graph.acquire() as conn:
        await graph.ensure_learner_node(conn)
        await graph.ensure_learner_node(conn)
    n = await _count(clean_graph, "MATCH (l:Learner) RETURN count(l)")
    assert n == 1


async def test_upsert_vocab_produces_edge_and_counter(
    clean_graph: asyncpg.Pool,
) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_graph.acquire() as conn:
        await graph.ensure_learner_node(conn)
        for i in range(3):
            await graph.upsert_vocab(conn, lemma="comer", at=at + timedelta(minutes=i))
    nodes = await _count(
        clean_graph, "MATCH (v:VocabItem {lemma: 'comer'}) RETURN count(v)"
    )
    edges = await _count(
        clean_graph,
        "MATCH (:Learner)-[r:PRODUCED]->(:VocabItem {lemma: 'comer'}) RETURN count(r)",
    )
    prod_count = await _count(
        clean_graph,
        "MATCH (v:VocabItem {lemma: 'comer'}) RETURN v.production_count",
    )
    assert nodes == 1
    assert edges == 1
    assert prod_count == 3


async def test_upsert_error_pattern_produces_edge_with_count(
    clean_graph: asyncpg.Pool,
) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_graph.acquire() as conn:
        await graph.ensure_learner_node(conn)
        for i in range(2):
            await graph.upsert_error_pattern(
                conn, category="ser_estar", at=at + timedelta(minutes=i)
            )
    nodes = await _count(
        clean_graph,
        "MATCH (e:ErrorPattern {category: 'ser_estar'}) RETURN count(e)",
    )
    edges = await _count(
        clean_graph,
        "MATCH (:Learner)-[r:MADE_ERROR]->(:ErrorPattern {category: 'ser_estar'}) "
        "RETURN count(r)",
    )
    edge_occurrences = await _count(
        clean_graph,
        "MATCH (:Learner)-[r:MADE_ERROR]->(:ErrorPattern {category: 'ser_estar'}) "
        "RETURN r.occurrences",
    )
    assert nodes == 1
    assert edges == 1
    assert edge_occurrences == 2


async def test_link_session_to_scenario(clean_graph: asyncpg.Pool) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_graph.acquire() as conn:
        await graph.ensure_learner_node(conn)
        await graph.link_session_to_scenario(
            conn, scenario_domain="pedir un café", band="A1", at=at
        )
        # Re-link with the same scenario: edge de-dupes.
        await graph.link_session_to_scenario(
            conn, scenario_domain="pedir un café", band="A1", at=at + timedelta(hours=1)
        )
    scenarios = await _count(
        clean_graph,
        "MATCH (s:Scenario {domain: 'pedir un café', band: 'A1'}) RETURN count(s)",
    )
    edges = await _count(
        clean_graph,
        "MATCH (:Learner)-[r:ENGAGED_WITH]->(:Scenario) RETURN count(r)",
    )
    assert scenarios == 1
    assert edges == 1


async def test_ensure_scenario_nodes_creates_one_per_theme(
    clean_graph: asyncpg.Pool,
) -> None:
    from hable_ya.learner.themes import THEMES_BY_LEVEL

    expected = sum(len(v) for v in THEMES_BY_LEVEL.values())
    async with clean_graph.acquire() as conn:
        await graph.ensure_scenario_nodes(conn)
        await graph.ensure_scenario_nodes(conn)  # idempotent
    actual = await _count(clean_graph, "MATCH (s:Scenario) RETURN count(s)")
    assert actual == expected


async def test_unsafe_identifier_is_skipped(clean_graph: asyncpg.Pool) -> None:
    """A lemma with a single quote is rejected — the graph stays empty."""
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_graph.acquire() as conn:
        await graph.ensure_learner_node(conn)
        await graph.upsert_vocab(conn, lemma="L'Hospitalet", at=at)
    nodes = await _count(clean_graph, "MATCH (v:VocabItem) RETURN count(v)")
    assert nodes == 0


# --------------------------------------------------------------------------- #
# Reads (spec #022). The graph's only reader — these exist so the day the
# writers silently stop, something fails. `_count` above stays the independent
# oracle: asserting the read primitive against itself would be circular.
# --------------------------------------------------------------------------- #


async def test_fetch_cypher_decodes_agtype_scalars(clean_graph: asyncpg.Pool) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_graph.acquire() as conn:
        await graph.ensure_learner_node(conn)
        await graph.upsert_vocab(conn, lemma="viajar", at=at)
        rows = await graph._fetch_cypher(
            conn,
            "MATCH (v:VocabItem) RETURN v.lemma AS lemma, v.production_count AS n",
            "lemma",
            "n",
        )
    # agtype arrives as a string with JSON quoting ('"viajar"', '1'); the
    # primitive must hand back real Python values, not quoted strings.
    assert rows == [{"lemma": "viajar", "n": 1}]
    assert isinstance(rows[0]["n"], int)


async def test_fetch_cypher_on_empty_graph_returns_no_rows(
    clean_graph: asyncpg.Pool,
) -> None:
    async with clean_graph.acquire() as conn:
        rows = await graph._fetch_cypher(
            conn, "MATCH (v:VocabItem) RETURN v.lemma AS lemma", "lemma"
        )
    assert rows == []


async def test_fetch_cypher_rejects_an_unsafe_column_name(
    clean_graph: asyncpg.Pool,
) -> None:
    """Reads inherit the writers' `_IDENT_RE` discipline (spec Key Decision 5)."""
    async with clean_graph.acquire() as conn:
        rows = await graph._fetch_cypher(
            conn,
            "MATCH (n) RETURN count(n) AS n",
            "n) AS (x agtype); DROP TABLE turns--",
        )
    assert rows == []
    # The filter refused the read rather than interpolating it.
    assert await _count(clean_graph, "MATCH (n) RETURN count(n)") == 0


async def test_graph_summary_counts_match_the_writers(
    clean_graph: asyncpg.Pool,
) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_graph.acquire() as conn:
        await graph.ensure_learner_node(conn)
        for lemma in ("viajar", "comer"):
            await graph.upsert_vocab(conn, lemma=lemma, at=at)
        await graph.upsert_vocab(conn, lemma="viajar", at=at)  # second production
        await graph.upsert_error_pattern(conn, category="ser_estar", at=at)
        await graph.link_session_to_scenario(
            conn, scenario_domain="pedir un café", band="A2", at=at
        )
        summary = await graph.graph_summary(conn)

    assert summary["graph"] == graph.GRAPH
    assert summary["nodes"]["Learner"] == 1
    assert summary["nodes"]["VocabItem"] == 2
    assert summary["nodes"]["ErrorPattern"] == 1
    assert summary["edges"]["PRODUCED"] == 2
    assert summary["edges"]["MADE_ERROR"] == 1
    assert summary["edges"]["ENGAGED_WITH"] == 1
    # Ordered by the node-level counter, so the twice-produced lemma leads.
    assert summary["top_vocab"][0] == {"lemma": "viajar", "production_count": 2}
    assert summary["top_error_patterns"] == [
        {"category": "ser_estar", "occurrences": 1}
    ]

    # Cross-checked against the independent oracle.
    assert summary["nodes"]["VocabItem"] == await _count(
        clean_graph, "MATCH (v:VocabItem) RETURN count(v)"
    )


async def test_graph_summary_reports_absent_labels_as_zero(
    clean_graph: asyncpg.Pool,
) -> None:
    """A fresh deployment must read as zeros, not a 500 and not a gap.

    Reporting `0` rather than omitting the key is what makes a label that
    stopped being written visible instead of merely absent.
    """
    async with clean_graph.acquire() as conn:
        summary = await graph.graph_summary(conn)

    assert set(summary["nodes"]) == set(graph.KNOWN_LABELS)
    assert set(summary["edges"]) == set(graph.KNOWN_EDGES)
    assert all(v == 0 for v in summary["nodes"].values())
    assert all(v == 0 for v in summary["edges"].values())
    assert summary["top_vocab"] == []
    assert summary["top_error_patterns"] == []
