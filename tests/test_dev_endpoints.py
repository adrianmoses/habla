"""Dev endpoints: /dev/observations (missing + ingest_failed + ring) and
/dev/learner (profile snapshot + top errors + top vocab + recent domains).

Uses ``httpx.AsyncClient`` + ``ASGITransport`` rather than FastAPI's
``TestClient`` — the latter runs handlers on its own thread/event loop, which
can't share the session-scoped ``db_pool`` without tripping asyncpg's
"another operation is in progress" guard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI

from api.routes.dev import router as dev_router
from hable_ya.runtime.observations import TurnObservationSink


def _app_with_state(pool: object, sink: TurnObservationSink) -> FastAPI:
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


async def test_observations_endpoint_returns_missing_and_ingest_failed(
    tmp_path: Path,
) -> None:
    sink = TurnObservationSink(tmp_path / "turns.jsonl")
    sink.missing = 2
    sink.ingest_failed = 1
    sink.band_missing = 3
    sink.leveling_failed = 1
    app = _app_with_state(pool=None, sink=sink)
    r = await _get(app, "/dev/observations")
    assert r.status_code == 200
    body = r.json()
    assert body["missing"] == 2
    assert body["ingest_failed"] == 1
    assert body["band_missing"] == 3
    assert body["leveling_failed"] == 1
    assert body["observations"] == []


async def test_learner_endpoint_populated_profile(
    clean_learner_state: asyncpg.Pool, tmp_path: Path
) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "UPDATE learner_profile SET sessions_completed = 3, band = 'B1' "
            "WHERE id = 1"
        )
        await conn.execute(
            "INSERT INTO error_counts (category, count, last_seen_at) "
            "VALUES ('ser_estar', 5, $1), ('agreement', 2, $1)",
            at,
        )
        await conn.execute(
            "INSERT INTO vocabulary_items (lemma, sample_form, production_count, "
            "first_seen_at, last_seen_at) VALUES ('comer', 'como', 3, $1, $1)",
            at,
        )
        await conn.execute(
            "INSERT INTO sessions "
            "(session_id, started_at, theme_domain, band_at_start) "
            "VALUES ('s1', $1, 'pedir un café', 'A1')",
            at,
        )

    sink = TurnObservationSink(tmp_path / "turns.jsonl")
    app = _app_with_state(pool=clean_learner_state, sink=sink)
    r = await _get(app, "/dev/learner")
    assert r.status_code == 200
    body = r.json()

    assert body["profile"]["band"] == "B1"
    assert body["profile"]["sessions_completed"] == 3
    assert body["profile"]["error_patterns"] == ["ser_estar", "agreement"]
    assert body["profile"]["vocab_strengths"] == ["comer"]

    assert body["top_errors"][0]["category"] == "ser_estar"
    assert body["top_errors"][0]["count"] == 5
    assert body["top_vocab"][0]["lemma"] == "comer"
    assert body["top_vocab"][0]["production_count"] == 3
    assert body["recent_theme_domains"] == ["pedir un café"]
    # Spec 049: new fields are present.
    assert body["profile"]["is_calibrated"] is False
    assert body["profile"]["stable_sessions_at_band"] == 0
    assert body["profile"]["last_band_change_at"] is None
    assert body["band_history"] == []
    assert body["recent_turn_bands"] == []


async def test_learner_endpoint_returns_503_without_pool(tmp_path: Path) -> None:
    sink = TurnObservationSink(tmp_path / "turns.jsonl")
    app = _app_with_state(pool=None, sink=sink)
    r = await _get(app, "/dev/learner")
    assert r.status_code == 503


async def test_learner_endpoint_cold_start(
    clean_learner_state: asyncpg.Pool, tmp_path: Path
) -> None:
    sink = TurnObservationSink(tmp_path / "turns.jsonl")
    app = _app_with_state(pool=clean_learner_state, sink=sink)
    r = await _get(app, "/dev/learner")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["sessions_completed"] == 0
    assert body["profile"]["error_patterns"] == []
    assert body["profile"]["vocab_strengths"] == []
    assert body["top_errors"] == []
    assert body["top_vocab"] == []
    assert body["recent_theme_domains"] == []
    # Spec 049: fresh DB → uncalibrated, no audit history, no band turns.
    assert body["profile"]["is_calibrated"] is False
    assert body["band_history"] == []
    assert body["recent_turn_bands"] == []
