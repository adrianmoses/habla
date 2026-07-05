"""Integration tests for the band_history audit table + LevelingService writes.

DB-backed (skipped automatically when Postgres is unreachable, per
``conftest.py``). Asserts:

* Migration applied cleanly: ``turns.cefr_band``,
  ``learner_profile.stable_sessions_at_band``, and ``band_history`` all
  exist with the expected shape.
* :func:`is_calibrated_async` returns False on a fresh DB and True after
  a placement row exists.
* :class:`LevelingService` writes the audit row + updates the profile in
  one transaction. ``stable_sessions_at_band`` resets on a flip.
* ``GET /dev/learner`` surfaces the recent 5 ``band_history`` rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI

from api.routes.dev import router as dev_router
from hable_ya.learner.leveling import LevelingService
from hable_ya.learner.profile import current_band, is_calibrated_async
from hable_ya.runtime.observations import TurnObservationSink


def _app(pool: asyncpg.Pool, sink: TurnObservationSink) -> FastAPI:
    app = FastAPI()
    app.state.db_pool = pool
    app.state.observation_sink = sink
    app.include_router(dev_router)
    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


async def test_migration_applied_band_columns_present(
    clean_learner_state: asyncpg.Pool,
) -> None:
    async with clean_learner_state.acquire() as conn:
        # turns.cefr_band exists.
        col = await conn.fetchval(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='turns' AND column_name='cefr_band'"
        )
        assert col == "cefr_band"
        # learner_profile.stable_sessions_at_band exists.
        col = await conn.fetchval(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='learner_profile' "
            "AND column_name='stable_sessions_at_band'"
        )
        assert col == "stable_sessions_at_band"
        # band_history table exists.
        rel = await conn.fetchval(
            "SELECT to_regclass('public.band_history')"
        )
        assert rel == "band_history"


async def test_is_calibrated_async_false_on_fresh_db(
    clean_learner_state: asyncpg.Pool,
) -> None:
    assert (await is_calibrated_async(clean_learner_state)) is False


async def test_placement_writes_band_history_and_flips_calibrated(
    clean_learner_state: asyncpg.Pool,
) -> None:
    leveling = LevelingService(clean_learner_state)
    # Seed a session row + four A2-banded turns so placement runs at modal A2.
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (session_id, band_at_start) "
            "VALUES ('placement_s1', 'A2')"
        )
        for i in range(4):
            await conn.execute(
                """
                INSERT INTO turns
                    (session_id, timestamp, learner_utterance, fluency_signal,
                     L1_used, cefr_band)
                VALUES ($1, $2, $3, 'moderate', false, 'A2')
                """,
                "placement_s1",
                datetime(2026, 4, 22, 12, i, 0, tzinfo=UTC),
                f"utt {i}",
            )

    decision = await leveling.run_placement(session_id="placement_s1")
    assert decision is not None
    assert decision.band == "A2"

    assert (await is_calibrated_async(clean_learner_state)) is True
    async with clean_learner_state.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT from_band, to_band, reason FROM band_history "
            "ORDER BY changed_at DESC LIMIT 1"
        )
        band = await current_band(clean_learner_state)
    assert row is not None
    assert row["from_band"] is None
    assert row["to_band"] == "A2"
    assert row["reason"] == "placement"
    assert band == "A2"


async def test_placement_abstains_when_too_few_valid_bands(
    clean_learner_state: asyncpg.Pool,
) -> None:
    leveling = LevelingService(clean_learner_state)
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (session_id, band_at_start) "
            "VALUES ('abstain_s1', 'A2')"
        )
        # Two valid bands + two NULL → below placement_min_valid_turns=3.
        for i, band in enumerate(["A2", None, None, "A2"]):
            await conn.execute(
                """
                INSERT INTO turns
                    (session_id, timestamp, learner_utterance, fluency_signal,
                     L1_used, cefr_band)
                VALUES ($1, $2, $3, 'moderate', false, $4)
                """,
                "abstain_s1",
                datetime(2026, 4, 22, 12, i, 0, tzinfo=UTC),
                f"utt {i}",
                band,
            )

    decision = await leveling.run_placement(session_id="abstain_s1")
    assert decision is None
    # Calibration stays False; subsequent session re-enters the diagnostic.
    assert (await is_calibrated_async(clean_learner_state)) is False
    async with clean_learner_state.acquire() as conn:
        history_count = await conn.fetchval(
            "SELECT count(*) FROM band_history"
        )
    assert history_count == 0


async def test_apply_band_change_resets_stable_sessions(
    clean_learner_state: asyncpg.Pool,
) -> None:
    leveling = LevelingService(clean_learner_state)
    # Seed stable_sessions_at_band > 0 so we observe the reset on flip.
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "UPDATE learner_profile SET stable_sessions_at_band = 5 "
            "WHERE id = 1"
        )
        await conn.execute(
            "INSERT INTO sessions (session_id, band_at_start) "
            "VALUES ('flip_s1', 'A2')"
        )
        for i in range(4):
            await conn.execute(
                """
                INSERT INTO turns
                    (session_id, timestamp, learner_utterance, fluency_signal,
                     L1_used, cefr_band)
                VALUES ($1, $2, $3, 'moderate', false, 'B1')
                """,
                "flip_s1",
                datetime(2026, 4, 22, 12, i, 0, tzinfo=UTC),
                f"utt {i}",
            )
    await leveling.run_placement(session_id="flip_s1")

    async with clean_learner_state.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT band, stable_sessions_at_band, last_band_change_at "
            "FROM learner_profile WHERE id = 1"
        )
    assert row is not None
    assert row["band"] == "B1"
    assert row["stable_sessions_at_band"] == 0
    assert row["last_band_change_at"] is not None


async def test_dev_learner_returns_band_history_rows(
    clean_learner_state: asyncpg.Pool, tmp_path: Path
) -> None:
    # Insert two band_history rows so the endpoint surfaces them in DESC order.
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO band_history
                (from_band, to_band, reason, signals, changed_at)
            VALUES
                (NULL, 'A2', 'placement', '{"k": 1}'::jsonb,
                 timestamp '2026-04-22 12:00:00+00'),
                ('A2', 'B1', 'auto_promote', '{"k": 2}'::jsonb,
                 timestamp '2026-04-23 12:00:00+00')
            """
        )

    sink = TurnObservationSink(tmp_path / "turns.jsonl")
    app = _app(clean_learner_state, sink)
    response = await _get(app, "/dev/learner")
    assert response.status_code == 200
    body = response.json()

    assert body["profile"]["is_calibrated"] is True
    history = body["band_history"]
    assert [r["reason"] for r in history] == ["auto_promote", "placement"]
    assert history[0]["to_band"] == "B1"
    assert history[1]["to_band"] == "A2"
    # recent_turn_bands shape is present (empty here).
    assert "recent_turn_bands" in body
