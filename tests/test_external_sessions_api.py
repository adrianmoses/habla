"""Contract tests for the La Libreta handoff API (spec #032)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI

from api.routes.external_sessions import router

SECRET = "la-libreta-secret"
BODY = {
    "source": "la-libreta",
    "sourceRef": "p02",
    "mode": "speaking",
    "text": "Describe una decisión.",
    "structures": ["condicional compuesto"],
    "target": "monólogo de 3 minutos",
    "date": "2026-05-02",
}


class _Acquire:
    def __init__(self, conn: object) -> None:
        self.conn = conn

    async def __aenter__(self) -> object:
        return self.conn

    async def __aexit__(self, *args: object) -> None:
        return None


class FakePool:
    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def acquire(self) -> _Acquire:
        return _Acquire(self)

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        self.calls.append((query, args))
        return self.rows.pop(0)


def _app(pool: object | None, *, integration_token: str = SECRET) -> FastAPI:
    app = FastAPI()
    app.state.db_pool = pool
    app.state.settings = SimpleNamespace(
        la_libreta_api_token=integration_token,
        public_base_url="https://habla.example.com/base-is-ignored",
        session_auth_token="learner-secret",
        session_auth_disabled=False,
    )
    app.include_router(router)
    return app


async def _post(
    app: FastAPI, body: object = BODY, *, bearer: str | None = SECRET
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/sessions", json=body, headers=headers)


async def test_create_requires_dedicated_token_before_db_access() -> None:
    assert (await _post(_app(None), bearer=None)).status_code == 401
    assert (await _post(_app(None), bearer="wrong")).status_code == 401


async def test_create_fails_closed_when_token_is_unset() -> None:
    response = await _post(_app(None, integration_token=""), bearer=SECRET)
    assert response.status_code == 401


async def test_create_returns_201_and_canonical_deep_link() -> None:
    created_at = datetime(2026, 5, 2, 7, 14, 22, tzinfo=UTC)
    pool = FakePool([{"id": "sess_abc", "created_at": created_at}])
    response = await _post(_app(pool), {**BODY, "futureMetadata": {"x": 1}})
    assert response.status_code == 201
    assert response.json() == {
        "id": "sess_abc",
        "url": "https://habla.example.com/session/sess_abc",
        "createdAt": "2026-05-02T07:14:22Z",
    }
    assert "INSERT INTO external_session_handoffs" in pool.calls[0][0]


async def test_replay_returns_existing_row_with_200() -> None:
    created_at = datetime(2026, 5, 2, 7, 14, 22, tzinfo=UTC)
    pool = FakePool([None, {"id": "sess_existing", "created_at": created_at}])
    response = await _post(_app(pool))
    assert response.status_code == 200
    assert response.json()["id"] == "sess_existing"
    assert len(pool.calls) == 2
    assert "WHERE source = $1" in pool.calls[1][0]


async def test_unknown_source_and_mode_are_rejected() -> None:
    source = await _post(_app(None), {**BODY, "source": "someone-else"})
    mode = await _post(_app(None), {**BODY, "mode": "listening"})
    assert source.status_code == 422
    assert mode.status_code == 422


async def test_learner_read_uses_learner_token_not_integration_token() -> None:
    pool = FakePool([])
    app = _app(pool)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        integration = await client.get(
            "/api/sessions/sess_abc",
            headers={"Authorization": f"Bearer {SECRET}"},
        )
    assert integration.status_code == 401
    assert pool.calls == []
