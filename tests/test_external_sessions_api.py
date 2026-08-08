"""Contract tests for the La Libreta handoff API (spec #033).

Everything here is exercised through HTTP against a fake pool, so it covers the
*wire* contract La Libreta codes against — statuses, aliases, forward
compatibility, and which credential opens which door. The behaviours that need
a real unique index (idempotency under concurrency) live in
``tests/test_external_sessions_db.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from api.routes.external_sessions import router

SECRET = "la-libreta-secret"
LEARNER_SECRET = "learner-secret"
ALLOWED = ("https://la-libreta.example.com",)
BODY = {
    "source": "la-libreta",
    "sourceRef": "p02",
    "mode": "speaking",
    "text": "Describe una decisión.",
    "structures": ["condicional compuesto"],
    "target": "monólogo de 3 minutos",
    "date": "2026-05-02",
}
CREATED_AT = datetime(2026, 5, 2, 7, 14, 22, tzinfo=UTC)


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "sess_abc",
        "source": "la-libreta",
        "source_ref": "p02",
        "source_date": date(2026, 5, 2),
        "mode": "speaking",
        "prompt_text": BODY["text"],
        "structures": BODY["structures"],
        "target": BODY["target"],
        "callback_url": None,
        "created_at": CREATED_AT,
        "started_at": None,
        "completed_at": None,
        "callback_attempts": 0,
        "callback_delivered_at": None,
    }
    row.update(overrides)
    return row


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


def _app(
    pool: object | None,
    *,
    integration_token: str = SECRET,
    callback_origins: tuple[str, ...] = ALLOWED,
) -> FastAPI:
    app = FastAPI()
    app.state.db_pool = pool
    app.state.settings = SimpleNamespace(
        la_libreta_api_token=integration_token,
        public_base_url="https://habla.example.com/base-is-ignored",
        callback_origins=callback_origins,
        callback_timeout_seconds=1.0,
        session_auth_token=LEARNER_SECRET,
        session_auth_disabled=False,
    )
    app.include_router(router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _post(
    app: FastAPI, body: object = BODY, *, bearer: str | None = SECRET
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    async with _client(app) as client:
        return await client.post("/api/sessions", json=body, headers=headers)


# --------------------------------------------------------------------------
# Authentication — the two credentials, and that neither substitutes for the
# other. This is #016's trust boundary restated at a new door.
# --------------------------------------------------------------------------


async def test_create_requires_dedicated_token_before_db_access() -> None:
    assert (await _post(_app(None), bearer=None)).status_code == 401
    assert (await _post(_app(None), bearer="wrong")).status_code == 401


async def test_create_fails_closed_when_token_is_unset() -> None:
    response = await _post(_app(None, integration_token=""), bearer=SECRET)
    assert response.status_code == 401


async def test_unauthorized_response_does_not_leak_the_expected_token() -> None:
    response = await _post(_app(None), bearer="wrong")
    assert SECRET not in response.text
    assert response.json() == {"detail": "unauthorized"}


async def test_learner_read_uses_learner_token_not_integration_token() -> None:
    pool = FakePool([])
    async with _client(_app(pool)) as client:
        integration = await client.get(
            "/api/sessions/sess_abc",
            headers={"Authorization": f"Bearer {SECRET}"},
        )
    assert integration.status_code == 401
    # Refused before the pool is touched — an unauthorized caller cannot even
    # probe which ids exist.
    assert pool.calls == []


async def test_integration_token_cannot_complete_a_session() -> None:
    pool = FakePool([])
    async with _client(_app(pool)) as client:
        response = await client.post(
            "/api/sessions/sess_abc/complete",
            headers={"Authorization": f"Bearer {SECRET}"},
        )
    assert response.status_code == 401
    assert pool.calls == []


# --------------------------------------------------------------------------
# Create: statuses, canonical URL, forward compatibility.
# --------------------------------------------------------------------------


async def test_create_returns_201_and_canonical_deep_link() -> None:
    pool = FakePool([_row()])
    response = await _post(_app(pool), {**BODY, "futureMetadata": {"x": 1}})
    assert response.status_code == 201
    assert response.json() == {
        "id": "sess_abc",
        "url": "https://habla.example.com/session/sess_abc",
        "createdAt": "2026-05-02T07:14:22Z",
    }
    assert "INSERT INTO external_session_handoffs" in pool.calls[0][0]


async def test_response_url_ignores_the_request_host_header() -> None:
    # The `url` is what La Libreta redirects a person's browser to, and this is
    # a server-to-server endpoint where `Host` is attacker-controlled.
    pool = FakePool([_row()])
    async with _client(_app(pool)) as client:
        response = await client.post(
            "/api/sessions",
            json=BODY,
            headers={
                "Authorization": f"Bearer {SECRET}",
                "Host": "evil.example.net",
                "X-Forwarded-Host": "evil.example.net",
            },
        )
    assert response.json()["url"].startswith("https://habla.example.com/session/")


async def test_replay_returns_existing_row_with_200() -> None:
    pool = FakePool([None, _row(id="sess_existing")])
    response = await _post(_app(pool))
    assert response.status_code == 200
    assert response.json()["id"] == "sess_existing"
    assert response.json()["createdAt"] == "2026-05-02T07:14:22Z"
    assert len(pool.calls) == 2
    assert "WHERE source = $1" in pool.calls[1][0]


async def test_replay_with_a_different_payload_keeps_the_stored_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """First payload wins, and the divergence is observable.

    Mutating the row would change what an already-open deep link means;
    rejecting it would break the upstream requirement to return the existing
    session. So: stable replay plus a warning naming only the fields.
    """
    pool = FakePool([None, _row(id="sess_existing")])
    with caplog.at_level(logging.WARNING):
        response = await _post(
            _app(pool), {**BODY, "text": "Otra consigna", "target": "5 minutos"}
        )

    assert response.status_code == 200
    assert response.json()["id"] == "sess_existing"
    # Only the INSERT and the SELECT ran — nothing updated the stored payload.
    assert len(pool.calls) == 2
    assert not any("UPDATE" in query for query, _ in pool.calls)

    warning = "\n".join(record.getMessage() for record in caplog.records)
    assert "text" in warning and "target" in warning
    assert "structures" not in warning  # unchanged fields are not reported
    assert SECRET not in warning
    assert "Otra consigna" not in warning  # field names, not payload contents


# --------------------------------------------------------------------------
# Validation. The upstream contract names 400, not FastAPI's default 422.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**BODY, "source": "someone-else"}, id="unknown-source"),
        pytest.param({**BODY, "mode": "listening"}, id="unknown-mode"),
        pytest.param({**BODY, "text": ""}, id="blank-text"),
        pytest.param({**BODY, "target": ""}, id="blank-target"),
        pytest.param({**BODY, "sourceRef": ""}, id="blank-source-ref"),
        pytest.param({**BODY, "structures": "condicional"}, id="structures-not-array"),
        pytest.param({**BODY, "structures": [1, 2]}, id="structures-not-strings"),
        pytest.param({**BODY, "date": "02/05/2026"}, id="malformed-date"),
        pytest.param({k: v for k, v in BODY.items() if k != "text"}, id="missing-text"),
        pytest.param(["not", "an", "object"], id="not-an-object"),
    ],
)
async def test_invalid_bodies_are_400_and_write_nothing(body: object) -> None:
    pool = FakePool([])
    response = await _post(_app(pool), body)
    assert response.status_code == 400
    assert pool.calls == []


async def test_malformed_json_is_400() -> None:
    pool = FakePool([])
    async with _client(_app(pool)) as client:
        response = await client.post(
            "/api/sessions",
            content=b"{not json",
            headers={
                "Authorization": f"Bearer {SECRET}",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 400
    assert pool.calls == []


async def test_unknown_top_level_fields_are_ignored_not_rejected() -> None:
    # Forward compatibility runs one way only: La Libreta may add fields
    # without a Habla release, but an unknown *enum value* is still a 400.
    pool = FakePool([_row()])
    response = await _post(
        _app(pool), {**BODY, "difficulty": "hard", "tags": ["dele", "b2"]}
    )
    assert response.status_code == 201


# --------------------------------------------------------------------------
# Callback destinations are policed at create time, before a row exists.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://la-libreta.example.com/cb", id="plain-http"),
        pytest.param("https://evil.example.net/cb", id="not-allowlisted"),
        pytest.param("https://127.0.0.1/cb", id="loopback"),
        pytest.param("https://169.254.169.254/latest/meta-data", id="link-local"),
        pytest.param("https://10.0.0.5/cb", id="private-network"),
        pytest.param("https://u:p@la-libreta.example.com/cb", id="credentials"),
        pytest.param("file:///etc/passwd", id="non-http-scheme"),
    ],
)
async def test_rejected_callback_destinations_are_400_and_write_nothing(
    url: str,
) -> None:
    pool = FakePool([])
    response = await _post(_app(pool), {**BODY, "callbackUrl": url})
    assert response.status_code == 400
    assert "callbackUrl" in response.json()["detail"]
    # The row is never written, so an unapproved destination cannot sit in the
    # database waiting to be fetched by a later completion.
    assert pool.calls == []


async def test_callback_is_rejected_when_no_origin_is_configured() -> None:
    pool = FakePool([])
    response = await _post(
        _app(pool, callback_origins=()),
        {**BODY, "callbackUrl": "https://la-libreta.example.com/cb"},
    )
    assert response.status_code == 400
    assert pool.calls == []


async def test_allowlisted_callback_is_stored() -> None:
    pool = FakePool([_row(callback_url="https://la-libreta.example.com/cb")])
    response = await _post(
        _app(pool), {**BODY, "callbackUrl": "https://la-libreta.example.com/cb"}
    )
    assert response.status_code == 201
    assert "https://la-libreta.example.com/cb" in pool.calls[0][1]


# --------------------------------------------------------------------------
# Read + complete: what the learner's browser sees and does.
# --------------------------------------------------------------------------


async def test_read_returns_the_contract_fields_and_no_integration_state() -> None:
    pool = FakePool([_row(callback_url="https://la-libreta.example.com/cb")])
    async with _client(_app(pool)) as client:
        response = await client.get(
            "/api/sessions/sess_abc",
            headers={"Authorization": f"Bearer {LEARNER_SECRET}"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == BODY["text"]
    assert payload["structures"] == BODY["structures"]
    assert payload["target"] == BODY["target"]
    assert payload["sourceRef"] == "p02"
    assert payload["completedAt"] is None
    # The browser has no business with the callback destination or its state,
    # and must never see the integration token.
    assert "callbackUrl" not in payload
    assert "callback_url" not in payload
    assert SECRET not in response.text


async def test_read_reports_an_unknown_id_as_404() -> None:
    pool = FakePool([None])
    async with _client(_app(pool)) as client:
        response = await client.get(
            "/api/sessions/sess_gone",
            headers={"Authorization": f"Bearer {LEARNER_SECRET}"},
        )
    assert response.status_code == 404


async def test_read_starts_nothing() -> None:
    # Reload safety: resolving a deep link is one SELECT. `started_at` is
    # stamped by the WebSocket handler, on an explicit start.
    pool = FakePool([_row()])
    async with _client(_app(pool)) as client:
        await client.get(
            "/api/sessions/sess_abc",
            headers={"Authorization": f"Bearer {LEARNER_SECRET}"},
        )
    assert len(pool.calls) == 1
    assert pool.calls[0][0].strip().startswith("SELECT")


async def test_complete_transitions_once_and_reports_completed_at() -> None:
    completed = datetime(2026, 5, 2, 7, 32, 11, tzinfo=UTC)
    pool = FakePool([_row(completed_at=completed)])
    async with _client(_app(pool)) as client:
        response = await client.post(
            "/api/sessions/sess_abc/complete",
            headers={"Authorization": f"Bearer {LEARNER_SECRET}"},
        )
    assert response.status_code == 200
    assert response.json()["completedAt"] == "2026-05-02T07:32:11Z"
    assert "UPDATE" in pool.calls[0][0]
    assert "completed_at IS NULL" in pool.calls[0][0]


async def test_complete_on_an_unknown_id_is_404() -> None:
    pool = FakePool([None, None])
    async with _client(_app(pool)) as client:
        response = await client.post(
            "/api/sessions/sess_gone/complete",
            headers={"Authorization": f"Bearer {LEARNER_SECRET}"},
        )
    assert response.status_code == 404
