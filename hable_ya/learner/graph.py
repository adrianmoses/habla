"""AGE cypher writers for the ``learner_knowledge`` graph.

Every function takes an ``asyncpg.Connection`` (not a pool) so the caller can
compose them inside a shared ``conn.transaction()`` alongside the relational
upserts. Counter upserts use ``MERGE (…) SET x = coalesce(x, 0) + 1`` because
AGE's cypher parser rejects the openCypher ``ON CREATE SET`` / ``ON MATCH SET``
clauses (`tests/test_age_spike.py` covers the working shape).

Identifier inputs (lemma, category, scenario domain, session id) are filtered
through :data:`_IDENT_RE` before reaching cypher — single quotes inside values
would break the dollar-quoted cypher body, and escaping them is error-prone.
Invalid inputs are logged and skipped rather than raising; the caller gets an
empty return, so a stray ``O'Brien`` lemma doesn't tear down the whole ingest
transaction.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import asyncpg

from eval.fixtures.schema import CEFRBand
from hable_ya.learner.themes import THEMES_BY_LEVEL

logger = logging.getLogger(__name__)

GRAPH = "learner_knowledge"

# Accept letters (including accented Spanish), digits, spaces, hyphens,
# underscores, periods, colons, and slashes (for ISO-8601 timestamps and
# domain-style identifiers like "viajar por trabajo vs. por placer").
# Explicitly rejects single quotes / backslashes which would break cypher's
# dollar-quoted string literal.
_IDENT_RE = re.compile(r"^[\w\sáéíóúñüÁÉÍÓÚÑÜ\-.:/+]+$")


def _safe(value: str) -> str | None:
    value = value.strip()
    if not value or not _IDENT_RE.fullmatch(value):
        return None
    return value


async def _run_cypher(conn: asyncpg.Connection, body: str) -> None:
    await conn.execute(
        f"SELECT * FROM cypher('{GRAPH}', $$ {body} $$) AS (v ag_catalog.agtype)"
    )


async def ensure_learner_node(conn: asyncpg.Connection) -> None:
    await _run_cypher(conn, "MERGE (l:Learner {id: 1})")


async def ensure_scenario_nodes(conn: asyncpg.Connection) -> None:
    """Seed one :Scenario node per ``THEMES_BY_LEVEL`` entry. Idempotent."""
    for band, themes in THEMES_BY_LEVEL.items():
        band_safe = _safe(band)
        assert band_safe is not None  # CEFRBand literals are always safe
        for theme in themes:
            domain = _safe(theme.domain)
            if domain is None:
                logger.warning(
                    "skipping scenario node — unsafe domain: %r", theme.domain
                )
                continue
            await _run_cypher(
                conn,
                f"MERGE (:Scenario {{domain: '{domain}', band: '{band_safe}'}})",
            )


async def upsert_vocab(conn: asyncpg.Connection, *, lemma: str, at: datetime) -> None:
    safe_lemma = _safe(lemma)
    safe_at = _safe(at.isoformat())
    if safe_lemma is None or safe_at is None:
        logger.warning("skipping vocab upsert — unsafe input (%r @ %s)", lemma, at)
        return
    await _run_cypher(
        conn,
        f"""
        MERGE (v:VocabItem {{lemma: '{safe_lemma}'}})
        SET v.production_count = coalesce(v.production_count, 0) + 1,
            v.last_seen_at = '{safe_at}'
        """,
    )
    await _run_cypher(
        conn,
        f"""
        MATCH (l:Learner {{id: 1}}), (v:VocabItem {{lemma: '{safe_lemma}'}})
        MERGE (l)-[r:PRODUCED]->(v)
        SET r.last_at = '{safe_at}'
        """,
    )


async def upsert_error_pattern(
    conn: asyncpg.Connection, *, category: str, at: datetime
) -> None:
    """Upsert `(:ErrorPattern)` + `(:Learner)-[:MADE_ERROR]->(:ErrorPattern)`.

    Counter property is `occurrences` rather than `count` because AGE's
    cypher parser rejects `SET x.count = …` — the identifier collides
    with the `count()` aggregate. The relational `error_counts.count`
    column is unaffected (SQL has no such collision).
    """
    safe_category = _safe(category)
    safe_at = _safe(at.isoformat())
    if safe_category is None or safe_at is None:
        logger.warning("skipping error upsert — unsafe input (%r @ %s)", category, at)
        return
    await _run_cypher(
        conn,
        f"""
        MERGE (e:ErrorPattern {{category: '{safe_category}'}})
        SET e.occurrences = coalesce(e.occurrences, 0) + 1,
            e.last_seen_at = '{safe_at}'
        """,
    )
    await _run_cypher(
        conn,
        f"""
        MATCH (l:Learner {{id: 1}}), (e:ErrorPattern {{category: '{safe_category}'}})
        MERGE (l)-[r:MADE_ERROR]->(e)
        SET r.occurrences = coalesce(r.occurrences, 0) + 1,
            r.last_at = '{safe_at}'
        """,
    )


async def link_session_to_scenario(
    conn: asyncpg.Connection,
    *,
    scenario_domain: str,
    band: CEFRBand,
    at: datetime,
) -> None:
    safe_domain = _safe(scenario_domain)
    safe_band = _safe(band)
    safe_at = _safe(at.isoformat())
    if safe_domain is None or safe_band is None or safe_at is None:
        logger.warning(
            "skipping scenario link — unsafe input (%r / %r / %s)",
            scenario_domain,
            band,
            at,
        )
        return
    await _run_cypher(
        conn,
        f"""
        MERGE (s:Scenario {{domain: '{safe_domain}', band: '{safe_band}'}})
        """,
    )
    await _run_cypher(
        conn,
        f"""
        MATCH (l:Learner {{id: 1}}),
              (s:Scenario {{domain: '{safe_domain}', band: '{safe_band}'}})
        MERGE (l)-[r:ENGAGED_WITH]->(s)
        SET r.last_at = '{safe_at}'
        """,
    )
