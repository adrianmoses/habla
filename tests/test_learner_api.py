"""Production learner-progress read API (spec #019).

Auth tests run DB-free (the Bearer gate runs before any DB access). Payload
tests use the session-scoped ``db_pool`` via ``clean_learner_state`` and the
same ``httpx.AsyncClient`` + ``ASGITransport`` pattern as
``test_dev_endpoints.py`` (FastAPI's ``TestClient`` runs handlers on its own
loop, which can't share the asyncpg pool).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from api.routes.learner import router as learner_router
from api.routes.session import _authorized
from hable_ya.auth import authorize_token
from hable_ya.learner.leveling import LevelingService


def _app(
    pool: object, *, token: str = "", disabled: bool = False
) -> FastAPI:
    app = FastAPI()
    app.state.db_pool = pool
    app.state.settings = SimpleNamespace(
        session_auth_token=token, session_auth_disabled=disabled
    )
    app.include_router(learner_router)
    return app


async def _get(
    app: FastAPI, path: str, *, bearer: str | None = None
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer is not None else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path, headers=headers)


# --------------------------------------------------------------------------- #
# Auth (no DB) — the Bearer gate runs before the handler, so an authorized
# request with no pool reaches the handler and 503s; unauthorized never does.
# --------------------------------------------------------------------------- #

SECRET = "s3cr3t-token"

PATHS = ["/api/learner", "/api/learner/sessions", "/api/learner/band-history"]


@pytest.mark.parametrize("path", PATHS)
async def test_missing_header_is_401(path: str) -> None:
    r = await _get(_app(pool=None, token=SECRET), path)
    assert r.status_code == 401


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Basic abc", "Bearer ", SECRET],  # malformed / non-bearer
)
async def test_malformed_authorization_is_401(header: str) -> None:
    app = _app(pool=None, token=SECRET)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/learner", headers={"Authorization": header})
    assert r.status_code == 401


async def test_wrong_token_is_401() -> None:
    r = await _get(_app(pool=None, token=SECRET), "/api/learner", bearer="nope")
    assert r.status_code == 401


async def test_fail_closed_when_secret_unset() -> None:
    # No configured secret and not disabled → refuse even a plausible token.
    r = await _get(_app(pool=None, token=""), "/api/learner", bearer="anything")
    assert r.status_code == 401


async def test_correct_token_passes_auth_then_503_without_pool() -> None:
    # Authorized → past the gate → handler's missing-pool guard fires (503,
    # not 401). Proves the token was accepted without needing a DB.
    r = await _get(_app(pool=None, token=SECRET), "/api/learner", bearer=SECRET)
    assert r.status_code == 503


async def test_disabled_bypasses_auth() -> None:
    r = await _get(_app(pool=None, disabled=True), "/api/learner")
    assert r.status_code == 503  # past the gate, no pool


async def test_token_never_echoed_in_response() -> None:
    r = await _get(_app(pool=None, token=SECRET), "/api/learner", bearer="wrong")
    assert SECRET not in r.text


# --------------------------------------------------------------------------- #
# Shared-helper regression: extracting authorize_token must not change the gate
# the WS endpoint's _authorized enforced.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "disabled,configured,presented",
    [
        (True, "", None),
        (True, "", "x"),
        (False, "", None),
        (False, "", "x"),
        (False, "sekret", None),
        (False, "sekret", "sekret"),
        (False, "sekret", "wrong"),
    ],
)
def test_authorize_token_matches_ws_authorized(
    disabled: bool, configured: str, presented: str | None
) -> None:
    settings = SimpleNamespace(
        session_auth_disabled=disabled, session_auth_token=configured
    )
    assert authorize_token(settings, presented) == _authorized(settings, presented)


# --------------------------------------------------------------------------- #
# Payload tests (DB) — reuse clean_learner_state; authorize via disabled=True.
# --------------------------------------------------------------------------- #


async def test_learner_profile_populated(
    clean_learner_state: asyncpg.Pool,
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
    app = _app(pool=clean_learner_state, disabled=True)
    r = await _get(app, "/api/learner")
    assert r.status_code == 200
    body = r.json()
    assert body["band"] == "B1"
    assert body["sessions_completed"] == 3
    assert body["error_patterns"] == ["ser_estar", "agreement"]
    assert body["vocab_strengths"] == ["comer"]
    assert body["top_errors"][0] == {
        "category": "ser_estar",
        "count": 5,
        "last_seen_at": at.isoformat(),
    }
    assert body["top_vocab"][0]["lemma"] == "comer"
    assert body["recent_theme_domains"] == ["pedir un café"]
    assert body["is_calibrated"] is False
    assert body["last_band_change_at"] is None


async def test_learner_profile_neutral_on_fresh_db(
    clean_learner_state: asyncpg.Pool,
) -> None:
    app = _app(pool=clean_learner_state, disabled=True)
    r = await _get(app, "/api/learner")
    assert r.status_code == 200
    body = r.json()
    assert body["band"] == "A2"
    assert body["sessions_completed"] == 0
    assert body["error_patterns"] == []
    assert body["vocab_strengths"] == []
    assert body["top_errors"] == []
    assert body["top_vocab"] == []
    assert body["recent_theme_domains"] == []
    assert body["is_calibrated"] is False


async def test_sessions_history_and_pagination(
    clean_learner_state: asyncpg.Pool,
) -> None:
    old = datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC)
    new = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (session_id, started_at, theme_domain, "
            "band_at_start) VALUES ('s_old', $1, 'viaje', 'A2'), "
            "('s_new', $2, 'comida', 'A2')",
            old,
            new,
        )
        # Two turns for s_new, none for s_old → LEFT JOIN keeps s_old at 0.
        for i in range(2):
            await conn.execute(
                "INSERT INTO turns (session_id, timestamp, learner_utterance, "
                "fluency_signal, L1_used) VALUES ('s_new', $1, $2, 'moderate', false)",
                datetime(2026, 4, 22, 12, i, 0, tzinfo=UTC),
                f"utt {i}",
            )
    app = _app(pool=clean_learner_state, disabled=True)

    r = await _get(app, "/api/learner/sessions")
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert [s["session_id"] for s in sessions] == ["s_new", "s_old"]  # newest first
    assert sessions[0]["turn_count"] == 2
    assert sessions[1]["turn_count"] == 0  # session with no turns still appears

    # Pagination: limit=1 → newest only; offset=1 → the older one.
    r1 = await _get(app, "/api/learner/sessions?limit=1")
    assert [s["session_id"] for s in r1.json()["sessions"]] == ["s_new"]
    r2 = await _get(app, "/api/learner/sessions?limit=1&offset=1")
    assert [s["session_id"] for s in r2.json()["sessions"]] == ["s_old"]


async def test_sessions_empty_on_fresh_db(
    clean_learner_state: asyncpg.Pool,
) -> None:
    app = _app(pool=clean_learner_state, disabled=True)
    r = await _get(app, "/api/learner/sessions")
    assert r.status_code == 200
    assert r.json()["sessions"] == []


async def test_band_history_empty_before_placement(
    clean_learner_state: asyncpg.Pool,
) -> None:
    app = _app(pool=clean_learner_state, disabled=True)
    r = await _get(app, "/api/learner/band-history")
    assert r.status_code == 200
    assert r.json()["band_history"] == []


async def test_band_history_after_placement(
    clean_learner_state: asyncpg.Pool,
) -> None:
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (session_id, band_at_start) "
            "VALUES ('placement_s1', 'A2')"
        )
        for i in range(4):
            await conn.execute(
                "INSERT INTO turns (session_id, timestamp, learner_utterance, "
                "fluency_signal, L1_used, cefr_band) "
                "VALUES ('placement_s1', $1, $2, 'moderate', false, 'A2')",
                datetime(2026, 4, 22, 12, i, 0, tzinfo=UTC),
                f"utt {i}",
            )
    decision = await LevelingService(clean_learner_state).run_placement(
        session_id="placement_s1"
    )
    assert decision is not None

    app = _app(pool=clean_learner_state, disabled=True)
    r = await _get(app, "/api/learner/band-history")
    assert r.status_code == 200
    rows = r.json()["band_history"]
    assert len(rows) == 1
    assert rows[0]["from_band"] is None
    assert rows[0]["to_band"] == "A2"
    assert rows[0]["reason"] == "placement"
    assert isinstance(rows[0]["signals"], dict)  # JSONB decoded, not a string


async def test_endpoints_503_without_pool() -> None:
    app = _app(pool=None, disabled=True)
    for path in PATHS:
        r = await _get(app, path)
        assert r.status_code == 503
