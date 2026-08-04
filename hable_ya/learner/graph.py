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

import json
import logging
import re
from datetime import datetime
from typing import Any

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


def _agtype(value: Any) -> Any:
    """Decode one AGE ``agtype`` column into a Python value.

    asyncpg has no codec for ``agtype``, so every column arrives as ``str`` —
    and string values keep their JSON quoting: ``label(n)`` comes back as
    ``'"Learner"'``, a count as ``'1'``. ``json.loads`` handles both, which is
    why it is used rather than ``int(str(...))`` — that works for counts and
    silently mangles labels.

    Vertices and edges stringify with an ``::vertex`` / ``::edge`` suffix that
    is not valid JSON; nothing here returns whole nodes (only scalars), so
    those fall through to the raw string rather than raising.
    """
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return value


async def _fetch_cypher(
    conn: asyncpg.Connection, body: str, *columns: str
) -> list[dict[str, Any]]:
    """Run a read-only cypher body and return decoded rows (spec #022).

    ``_run_cypher`` uses ``conn.execute`` and so cannot return rows — reads
    need their own primitive. AGE requires the result columns to be declared in
    the ``AS (...)`` clause, which is why they are a parameter rather than
    inferred.

    ``columns`` are interpolated into SQL, so they are call-site literals only:
    every caller in this module passes fixed names. They are filtered through
    :func:`_safe` anyway, on the same principle as the writers — the filter is
    cheap and the day someone threads a variable through here, it holds.
    """
    for column in columns:
        if _safe(column) is None:
            logger.warning("refusing cypher read — unsafe column name: %r", column)
            return []
    declared = ", ".join(f"{c} ag_catalog.agtype" for c in columns)
    rows = await conn.fetch(
        f"SELECT * FROM cypher('{GRAPH}', $$ {body} $$) AS ({declared})"
    )
    return [{c: _agtype(row[c]) for c in columns} for row in rows]


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


# --------------------------------------------------------------------------- #
# Reads (spec #022)
#
# The graph is an inspection artifact: nothing here feeds adaptation, which is
# relational (`learner/read.py`, `aggregations.py`, `leveling/policy.py`). This
# exists so the graph is a *verifiable* artifact rather than a write-only sink
# — without a read, nothing would ever detect the day the writers stop.
# --------------------------------------------------------------------------- #

#: Labels the writers above create. Reported even at zero, so a label that
#: stopped being written reads as `0` rather than vanishing from the payload.
KNOWN_LABELS = ("Learner", "Scenario", "VocabItem", "ErrorPattern")

#: Edge types the writers above create. Same zero-reporting rule.
KNOWN_EDGES = ("PRODUCED", "MADE_ERROR", "ENGAGED_WITH")

TOP_NODES = 10


async def graph_summary(conn: asyncpg.Connection) -> dict[str, Any]:
    """Node/edge counts and the top counter-bearing nodes.

    The top-node counters are the ones stored *on the node*
    (``v.production_count``, ``e.occurrences``), which duplicate
    ``vocabulary_items.production_count`` and ``error_counts.count``. That
    duplication is deliberately surfaced rather than hidden: it is the concrete
    shape of the modelling problem #021 Key Decision 4 recorded, and an
    operator comparing the two side by side is how it stays visible.
    """
    label_rows = await _fetch_cypher(
        conn, "MATCH (n) RETURN label(n) AS label, count(*) AS n", "label", "n"
    )
    edge_rows = await _fetch_cypher(
        conn, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n", "type", "n"
    )
    vocab = await _fetch_cypher(
        conn,
        f"""
        MATCH (v:VocabItem)
        RETURN v.lemma AS lemma, v.production_count AS n
        ORDER BY v.production_count DESC LIMIT {TOP_NODES}
        """,
        "lemma",
        "n",
    )
    errors = await _fetch_cypher(
        conn,
        f"""
        MATCH (e:ErrorPattern)
        RETURN e.category AS category, e.occurrences AS n
        ORDER BY e.occurrences DESC LIMIT {TOP_NODES}
        """,
        "category",
        "n",
    )

    seen_labels = {str(r["label"]): int(r["n"]) for r in label_rows}
    seen_edges = {str(r["type"]): int(r["n"]) for r in edge_rows}
    return {
        "graph": GRAPH,
        "nodes": {label: seen_labels.get(label, 0) for label in KNOWN_LABELS},
        "edges": {edge: seen_edges.get(edge, 0) for edge in KNOWN_EDGES},
        "top_vocab": [{"lemma": r["lemma"], "production_count": r["n"]} for r in vocab],
        "top_error_patterns": [
            {"category": r["category"], "occurrences": r["n"]} for r in errors
        ],
    }
