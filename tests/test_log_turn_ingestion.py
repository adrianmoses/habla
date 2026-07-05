"""End-to-end ingestion: TurnObservation → relational + AGE graph."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest_asyncio

from hable_ya.learner import graph
from hable_ya.learner.ingest import TurnIngestService
from hable_ya.learner.leveling import LevelingService
from hable_ya.learner.profile import current_band, is_calibrated_async
from hable_ya.runtime.observations import TurnObservation, TurnObservationSink


@pytest_asyncio.fixture
async def ingest_ready(clean_learner_state: asyncpg.Pool) -> asyncpg.Pool:
    """On top of the shared clean state, seed the `Learner` graph node so
    downstream MATCH clauses resolve."""
    async with clean_learner_state.acquire() as conn:
        await graph.ensure_learner_node(conn)
    return clean_learner_state


async def _count(pool: asyncpg.Pool, cypher_body: str) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT * FROM cypher('{graph.GRAPH}', $$ {cypher_body} $$) "
            f"AS (c ag_catalog.agtype)"
        )
    assert row is not None
    return int(str(row["c"]))


def _obs(
    *,
    session_id: str = "int_session_1",
    utterance: str = "quiero comer manzanas todos los días",
    errors: list[dict[str, str]] | None = None,
    fluency: str = "moderate",
    l1: bool = False,
    at: datetime | None = None,
    cefr_band: str | None = None,
) -> TurnObservation:
    at = at or datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    return TurnObservation(
        session_id=session_id,
        timestamp_iso=at.isoformat(),
        learner_utterance=utterance,
        errors=errors or [],
        fluency_signal=fluency,
        L1_used=l1,
        cefr_band=cefr_band,
    )


async def test_ingest_populates_turns_errors_vocab_and_graph(
    ingest_ready: asyncpg.Pool,
) -> None:
    ingest = TurnIngestService(ingest_ready)
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    obs = _obs(
        errors=[{"type": "ser_estar", "produced_form": "soy", "target_form": "estoy"}],
        at=at,
    )
    await ingest.ingest(obs)

    async with ingest_ready.acquire() as conn:
        turn_rows = await conn.fetch("SELECT session_id FROM turns")
        error_rows = await conn.fetch("SELECT category, count FROM error_counts")
        vocab_rows = await conn.fetch(
            "SELECT lemma, production_count FROM vocabulary_items"
        )

    assert len(turn_rows) == 1
    assert turn_rows[0]["session_id"] == "int_session_1"
    assert {(r["category"], r["count"]) for r in error_rows} == {("ser_estar", 1)}
    vocab_map = {r["lemma"]: r["production_count"] for r in vocab_rows}
    assert {"querer", "comer", "manzana", "día"} <= set(vocab_map)

    err_nodes = await _count(
        ingest_ready,
        "MATCH (:Learner)-[:MADE_ERROR]->(e:ErrorPattern {category: 'ser_estar'}) "
        "RETURN count(e)",
    )
    assert err_nodes == 1
    vocab_edges = await _count(
        ingest_ready,
        "MATCH (:Learner)-[:PRODUCED]->(v:VocabItem) RETURN count(v)",
    )
    assert vocab_edges >= 4


async def test_second_turn_increments_without_duplication(
    ingest_ready: asyncpg.Pool,
) -> None:
    ingest = TurnIngestService(ingest_ready)
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    err = [{"type": "ser_estar", "produced_form": "a", "target_form": "b"}]
    await ingest.ingest(_obs(errors=err, at=at))
    await ingest.ingest(_obs(errors=err, at=at.replace(minute=5)))

    async with ingest_ready.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count FROM error_counts WHERE category = 'ser_estar'"
        )
        turns = await conn.fetchval("SELECT count(*) FROM turns")
    assert count == 2
    assert turns == 2

    vocab_count = await _count(
        ingest_ready,
        "MATCH (v:VocabItem {lemma: 'comer'}) RETURN v.production_count",
    )
    assert vocab_count == 2


async def test_start_session_creates_session_row_and_scenario_edge(
    clean_learner_state: asyncpg.Pool,
) -> None:
    ingest = TurnIngestService(clean_learner_state)
    await ingest.start_session(
        session_id="sess_x",
        theme_domain="pedir un café",
        band="A1",
    )
    async with clean_learner_state.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT theme_domain, band_at_start FROM sessions "
            "WHERE session_id = 'sess_x'"
        )
        sessions_completed = await conn.fetchval(
            "SELECT sessions_completed FROM learner_profile WHERE id = 1"
        )
    assert row is not None
    assert row["theme_domain"] == "pedir un café"
    assert row["band_at_start"] == "A1"
    assert sessions_completed == 1

    scenario_edges = await _count(
        clean_learner_state,
        "MATCH (:Learner)-[:ENGAGED_WITH]->(:Scenario {domain: 'pedir un café'}) "
        "RETURN count(*)",
    )
    assert scenario_edges == 1


async def test_end_session_sets_ended_at(clean_learner_state: asyncpg.Pool) -> None:
    ingest = TurnIngestService(clean_learner_state)
    await ingest.start_session(
        session_id="sess_end",
        theme_domain="pedir un café",
        band="A1",
    )
    await ingest.end_session(session_id="sess_end")
    async with clean_learner_state.acquire() as conn:
        ended = await conn.fetchval(
            "SELECT ended_at FROM sessions WHERE session_id = 'sess_end'"
        )
    assert ended is not None


# ---- Spec 049: end-of-session placement + auto-leveling -----------------


async def _ingest_session(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    bands: list[str | None],
    base_minute: int = 0,
) -> TurnIngestService:
    """Run start_session + ingest()×N + end_session through the full path."""
    leveling = LevelingService(pool)
    sink = TurnObservationSink(Path("/tmp/spec049_test_turns.jsonl"))
    ingest = TurnIngestService(pool, leveling=leveling, sink=sink)
    await ingest.start_session(
        session_id=session_id,
        theme_domain="conversación abierta",
        band="A2",
    )
    for i, band in enumerate(bands):
        at = datetime(2026, 4, 22, 12, base_minute + i, 0, tzinfo=UTC)
        await ingest.ingest(
            _obs(
                session_id=session_id,
                utterance=f"utt {session_id} {i}",
                at=at,
                cefr_band=band,
            )
        )
    await ingest.end_session(session_id=session_id)
    return ingest


async def test_first_session_runs_placement_and_calibrates(
    ingest_ready: asyncpg.Pool,
) -> None:
    await _ingest_session(
        ingest_ready,
        session_id="placement1",
        bands=["A1", "A1", "A1", "A1"],
    )
    # Floor at default_learner_band (A2) lifts an all-A1 placement.
    band = await current_band(ingest_ready)
    assert band == "A2"
    assert (await is_calibrated_async(ingest_ready)) is True
    async with ingest_ready.acquire() as conn:
        reason = await conn.fetchval(
            "SELECT reason FROM band_history ORDER BY changed_at DESC LIMIT 1"
        )
    assert reason == "placement"


async def test_three_above_band_sessions_promote_at_K(
    ingest_ready: asyncpg.Pool,
) -> None:
    """Placement at A2, then 3 sessions of B2 turns → auto_promote on session 4.

    Mirrors the spec's manual validation #7: three above-band sessions; band
    flips on the third (placement + 3 promote-target = 4 total sessions).
    """
    # Session 1: placement at A2 (floor). All-A2 turns.
    await _ingest_session(
        ingest_ready,
        session_id="ladder_s1",
        bands=["A2", "A2", "A2", "A2"],
        base_minute=0,
    )
    assert (await current_band(ingest_ready)) == "A2"

    # Sessions 2, 3, 4: all-B2 turns. K=3 promote-target sessions in a row.
    for n in range(2, 5):
        await _ingest_session(
            ingest_ready,
            session_id=f"ladder_s{n}",
            bands=["B2", "B2", "B2", "B2"],
            base_minute=n * 10,
        )

    band = await current_band(ingest_ready)
    assert band == "B2"
    async with ingest_ready.acquire() as conn:
        rows = await conn.fetch(
            "SELECT reason FROM band_history ORDER BY changed_at ASC"
        )
    reasons = [r["reason"] for r in rows]
    assert reasons == ["placement", "auto_promote"]


async def test_post_placement_all_null_bands_are_no_op(
    ingest_ready: asyncpg.Pool,
) -> None:
    # Placement at A2.
    await _ingest_session(
        ingest_ready,
        session_id="np_s1",
        bands=["A2", "A2", "A2", "A2"],
        base_minute=0,
    )
    # Subsequent session — all turns omit cefr_band (model didn't emit).
    await _ingest_session(
        ingest_ready,
        session_id="np_s2",
        bands=[None, None, None, None],
        base_minute=10,
    )
    # Band unchanged. No new band_history row.
    assert (await current_band(ingest_ready)) == "A2"
    async with ingest_ready.acquire() as conn:
        history_count = await conn.fetchval(
            "SELECT count(*) FROM band_history"
        )
    assert history_count == 1  # only the placement row


async def test_leveling_failure_is_swallowed_and_counter_increments(
    ingest_ready: asyncpg.Pool,
) -> None:
    """A failure inside leveling at end_session must not propagate.

    Simulated by passing a ``LevelingService`` whose ``run_placement``
    raises. The end_session code catches and bumps the sink counter.
    """
    sink = TurnObservationSink(Path("/tmp/spec049_test_turns_fail.jsonl"))

    class _BoomLeveling:
        async def run_placement(self, *, session_id: str) -> None:
            raise RuntimeError("simulated leveling outage")

        async def run_leveling(self, *, current_band: str) -> None:  # pragma: no cover
            raise RuntimeError("simulated leveling outage")

    ingest = TurnIngestService(
        ingest_ready,
        leveling=_BoomLeveling(),  # type: ignore[arg-type]
        sink=sink,
    )
    await ingest.start_session(
        session_id="boom_s1",
        theme_domain="conversación abierta",
        band="A2",
    )
    # No exception escapes; the counter increments.
    await ingest.end_session(session_id="boom_s1")
    assert sink.leveling_failed == 1
    # Calibration stays False.
    assert (await is_calibrated_async(ingest_ready)) is False
