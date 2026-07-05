"""Lifecycle tests for /health and /ws/session warmup gating.

Uses TestClient with lifespan. Services, LLM warmup, and DB calls are patched
so the test doesn't need CUDA, model downloads, a live llama.cpp endpoint, or
Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from hable_ya.config import Settings


def _fake_load_services(_settings: Settings) -> Any:
    return MagicMock(name="fake-services")


async def _noop_warmup(*_args: Any, **_kwargs: Any) -> None:
    return None


@contextmanager
def _patched_app(db_reachable: bool = True) -> Iterator[TestClient]:
    fake_pool = MagicMock(name="fake-pool")
    fake_db = MagicMock(name="fake-db")
    fake_db.ping = AsyncMock(return_value=db_reachable)
    with (
        patch("api.main.load_services", _fake_load_services),
        patch("api.main.warmup_llm", _noop_warmup),
        patch("api.main.upgrade_to_head", AsyncMock(return_value=None)),
        patch("api.main.open_pool", AsyncMock(return_value=fake_pool)),
        patch("api.main.close_pool", AsyncMock(return_value=None)),
        patch("api.main.HableYaDB", MagicMock(return_value=fake_db)),
    ):
        from api.main import app

        with TestClient(app) as client:
            yield client


@pytest.fixture
def ready_app() -> Iterator[TestClient]:
    with _patched_app() as client:
        yield client


def test_health_returns_200_after_warmup(ready_app: TestClient) -> None:
    response = ready_app.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "llm_backend" in body


def test_health_returns_503_before_warmup_completes() -> None:
    with _patched_app() as client:
        from api.main import app

        app.state.ready = False
        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "warming_up"


def test_health_returns_503_when_db_unreachable() -> None:
    with _patched_app(db_reachable=False) as client:
        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "db_unreachable"


def test_ws_session_refused_while_warming_up() -> None:
    with _patched_app() as client:
        from api.main import app

        app.state.ready = False
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/ws/session"):
                pass
        assert excinfo.value.code == 1013
