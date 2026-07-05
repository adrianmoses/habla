"""LearnerProfileRepo — DB integration tests.

The aggregation rules are tested in `test_aggregations_shared.py`. This file
covers the repo's responsibilities: shaping SQL rows into the inputs that
`compute_snapshot` expects, applying the rolling window via SQL LIMIT, and
the small mutation methods.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import asyncpg
import pytest

from hable_ya.learner.aggregations import compute_snapshot
from hable_ya.learner.profile import LearnerProfileRepo


async def _insert_session(
    pool: asyncpg.Pool, session_id: str = "s1", band: str = "A2"
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (session_id, band_at_start) VALUES ($1, $2)",
            session_id,
            band,
        )


async def _insert_turn(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    at: datetime,
    fluency: str,
    l1_used: bool,
    utterance: str = "x",
) -> int:
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                """
                INSERT INTO turns
                    (session_id, timestamp, learner_utterance, fluency_signal, L1_used)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                session_id,
                at,
                utterance,
                fluency,
                l1_used,
            )
        )


async def test_cold_start_snapshot_uses_neutral_defaults(
    clean_learner_state: asyncpg.Pool,
) -> None:
    repo = LearnerProfileRepo(clean_learner_state)
    snapshot = await repo.get()
    assert snapshot.band == "A2"
    assert snapshot.sessions_completed == 0
    assert snapshot.l1_reliance == 0.5
    assert snapshot.speech_fluency == 0.5
    assert snapshot.error_patterns == []
    assert snapshot.vocab_strengths == []


async def test_window_limits_to_most_recent_turns(
    clean_learner_state: asyncpg.Pool,
) -> None:
    """Validates the SQL ORDER BY timestamp DESC LIMIT N — the repo's job."""
    await _insert_session(clean_learner_state)
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    await _insert_turn(
        clean_learner_state,
        session_id="s1",
        at=base.replace(hour=10),
        fluency="strong",
        l1_used=False,
    )
    for i in range(3):
        await _insert_turn(
            clean_learner_state,
            session_id="s1",
            at=base.replace(minute=i),
            fluency="weak",
            l1_used=True,
        )

    repo = LearnerProfileRepo(clean_learner_state)
    snapshot = await repo.get(window_turns=3)
    assert snapshot.l1_reliance == pytest.approx(1.0)
    assert snapshot.speech_fluency == pytest.approx(0.3)


async def test_repo_delegates_to_compute_snapshot(
    clean_learner_state: asyncpg.Pool,
) -> None:
    """Equivalence guard: repo.get and compute_snapshot agree on the same DB state.

    This is the contract that lets the agent-eval accumulator share the
    aggregation core without drifting from production.
    """
    await _insert_session(clean_learner_state)
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    turns = [
        ("weak", True),
        ("moderate", False),
        ("strong", True),
        ("weak", False),
    ]
    for i, (fluency, l1) in enumerate(turns):
        await _insert_turn(
            clean_learner_state,
            session_id="s1",
            at=base.replace(minute=i),
            fluency=fluency,
            l1_used=l1,
        )

    err_at = base.replace(hour=11)
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "INSERT INTO error_counts (category, count, last_seen_at) VALUES "
            "('ser_estar', 5, $1), ('agreement', 3, $1), ('tense', 1, $1)",
            err_at,
        )
        for i, lemma in enumerate(["alpha", "beta", "gamma"]):
            last_seen = base.replace(minute=i)
            await conn.execute(
                "INSERT INTO vocabulary_items (lemma, sample_form, "
                "production_count, first_seen_at, last_seen_at) "
                "VALUES ($1, $1, 1, $2, $2)",
                lemma,
                last_seen,
            )

    repo = LearnerProfileRepo(clean_learner_state)
    repo_snapshot = await repo.get(window_turns=20, top_errors=3, top_vocab=3)

    # Reconstruct compute_snapshot inputs from the same DB state.
    async with clean_learner_state.acquire() as conn:
        turn_rows = await conn.fetch(
            "SELECT L1_used, fluency_signal FROM turns "
            "ORDER BY timestamp DESC LIMIT 20"
        )
        error_rows = await conn.fetch(
            "SELECT category, count, last_seen_at FROM error_counts"
        )
        vocab_rows = await conn.fetch(
            "SELECT lemma, last_seen_at FROM vocabulary_items "
            "ORDER BY last_seen_at DESC LIMIT 3"
        )

    direct = compute_snapshot(
        band="A2",
        sessions_completed=0,
        l1_used_flags=[bool(r["l1_used"]) for r in turn_rows],
        fluency_signals=[r["fluency_signal"] for r in turn_rows],
        error_counter=Counter(
            {r["category"]: int(r["count"]) for r in error_rows}
        ),
        error_last_seen={r["category"]: r["last_seen_at"] for r in error_rows},
        vocab_last_seen={r["lemma"]: r["last_seen_at"] for r in vocab_rows},
        top_errors=3,
        top_vocab=3,
    )
    assert repo_snapshot == direct


async def test_increment_session_count(clean_learner_state: asyncpg.Pool) -> None:
    repo = LearnerProfileRepo(clean_learner_state)
    before = (await repo.get()).sessions_completed
    await repo.increment_session_count()
    await repo.increment_session_count()
    after = (await repo.get()).sessions_completed
    assert after == before + 2


async def test_set_band_persists(clean_learner_state: asyncpg.Pool) -> None:
    repo = LearnerProfileRepo(clean_learner_state)
    await repo.set_band("B1")
    snapshot = await repo.get()
    assert snapshot.band == "B1"
