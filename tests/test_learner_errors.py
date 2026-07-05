"""ErrorRepo — per-turn writes + top-N reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg

from hable_ya.learner.errors import ErrorRepo


async def _insert_session_and_turn(
    pool: asyncpg.Pool,
    session_id: str = "s1",
    *,
    at: datetime | None = None,
) -> int:
    at = at or datetime.now(tz=UTC)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (session_id, band_at_start) VALUES ($1, 'A2') "
            "ON CONFLICT DO NOTHING",
            session_id,
        )
        return int(
            await conn.fetchval(
                "INSERT INTO turns (session_id, timestamp, learner_utterance, "
                "fluency_signal, L1_used) VALUES ($1, $2, 'x', 'moderate', false) "
                "RETURNING id",
                session_id,
                at,
            )
        )


async def test_record_writes_observation_and_increments_count(
    clean_learner_state: asyncpg.Pool,
) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    turn_id = await _insert_session_and_turn(clean_learner_state, at=at)
    errors = [
        {
            "type": "ser_estar",
            "produced_form": "soy triste",
            "target_form": "estoy triste",
        },
        {
            "type": "agreement",
            "produced_form": "la problema",
            "target_form": "el problema",
        },
    ]
    async with clean_learner_state.acquire() as conn:
        async with conn.transaction():
            categories = await ErrorRepo.record(
                conn, turn_id=turn_id, errors=errors, at=at
            )
    assert set(categories) == {"ser_estar", "agreement"}

    async with clean_learner_state.acquire() as conn:
        obs = await conn.fetch(
            "SELECT category FROM error_observations WHERE turn_id = $1",
            turn_id,
        )
        counts = await conn.fetch(
            "SELECT category, count FROM error_counts ORDER BY category"
        )
    assert {r["category"] for r in obs} == {"ser_estar", "agreement"}
    assert [(r["category"], r["count"]) for r in counts] == [
        ("agreement", 1),
        ("ser_estar", 1),
    ]


async def test_record_handles_duplicate_categories_within_one_turn(
    clean_learner_state: asyncpg.Pool,
) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    turn_id = await _insert_session_and_turn(clean_learner_state, at=at)
    errors = [
        {"type": "ser_estar", "produced_form": "soy", "target_form": "estoy"},
        {"type": "ser_estar", "produced_form": "es bien", "target_form": "está bien"},
    ]
    async with clean_learner_state.acquire() as conn:
        async with conn.transaction():
            await ErrorRepo.record(conn, turn_id=turn_id, errors=errors, at=at)
        obs = await conn.fetch(
            "SELECT count(*) AS n FROM error_observations WHERE category = 'ser_estar'"
        )
        count = await conn.fetchval(
            "SELECT count FROM error_counts WHERE category = 'ser_estar'"
        )
    assert obs[0]["n"] == 2
    # Distinct categories in the turn increment once, not per-observation.
    assert count == 1


async def test_record_across_multiple_turns_accumulates(
    clean_learner_state: asyncpg.Pool,
) -> None:
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    err = [{"type": "ser_estar", "produced_form": "a", "target_form": "b"}]
    for i in range(3):
        turn_id = await _insert_session_and_turn(
            clean_learner_state, at=base + timedelta(minutes=i)
        )
        async with clean_learner_state.acquire() as conn:
            async with conn.transaction():
                await ErrorRepo.record(
                    conn,
                    turn_id=turn_id,
                    errors=err,
                    at=base + timedelta(minutes=i),
                )
    async with clean_learner_state.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count FROM error_counts WHERE category = 'ser_estar'"
        )
    assert count == 3


async def test_top_categories_ordering(clean_learner_state: asyncpg.Pool) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "INSERT INTO error_counts (category, count, last_seen_at) VALUES "
            "('a', 5, $1), ('b', 5, $2), ('c', 2, $1)",
            at,
            at + timedelta(minutes=1),
        )
        top = await ErrorRepo.top_categories(conn, limit=2)
    # Tie on count → broken by last_seen_at DESC → b before a.
    assert top == ["b", "a"]


async def test_record_skips_empty_and_missing_types(
    clean_learner_state: asyncpg.Pool,
) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    turn_id = await _insert_session_and_turn(clean_learner_state, at=at)
    errors = [
        {"type": "", "produced_form": "x", "target_form": "y"},
        {"produced_form": "x", "target_form": "y"},
        {"type": "keeper", "produced_form": "x", "target_form": "y"},
    ]
    async with clean_learner_state.acquire() as conn:
        async with conn.transaction():
            categories = await ErrorRepo.record(
                conn, turn_id=turn_id, errors=errors, at=at
            )
    assert categories == ["keeper"]
