"""Unit tests for #016 auth, fail-fast, and single-session enforcement.

The full eviction path (real PipelineTask cancellation propagating through
`task.run`) is the live spike in the spec; here we deterministically cover the
pure logic: auth decisions, token extraction, secret fail-fast, provider
classification, and the swap/identity-guard/evict helpers.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.main import require_cloud_secrets
from api.routes.session import (
    ActiveSession,
    _authorized,
    _clear_active,
    _evict,
    _extract_token,
    _install_active,
    _provider_for_exception,
)


def _settings(**kw: object) -> SimpleNamespace:
    base = {"session_auth_token": "", "session_auth_disabled": False}
    base.update(kw)
    return SimpleNamespace(**base)


class TestAuthorized:
    def test_disabled_allows_anything(self) -> None:
        assert _authorized(_settings(session_auth_disabled=True), None) is True

    def test_fail_closed_when_token_unset(self) -> None:
        # No token configured and not disabled → refuse (the whole point).
        assert _authorized(_settings(), "anything") is False
        assert _authorized(_settings(), None) is False

    def test_matching_token(self) -> None:
        s = _settings(session_auth_token="s3cret")
        assert _authorized(s, "s3cret") is True

    def test_mismatched_or_missing_token(self) -> None:
        s = _settings(session_auth_token="s3cret")
        assert _authorized(s, "wrong") is False
        assert _authorized(s, None) is False


class TestExtractToken:
    def _ws(self, query: dict[str, str], headers: dict[str, str]) -> SimpleNamespace:
        return SimpleNamespace(query_params=query, headers=headers)

    def test_query_param(self) -> None:
        token, sub = _extract_token(self._ws({"token": "abc"}, {}))
        assert token == "abc" and sub is None

    def test_subprotocol(self) -> None:
        token, sub = _extract_token(
            self._ws({}, {"sec-websocket-protocol": "tok123, other"})
        )
        assert token == "tok123" and sub == "tok123"  # echoed back on accept

    def test_none(self) -> None:
        assert _extract_token(self._ws({}, {})) == (None, None)


class TestProviderClassification:
    def test_by_module(self) -> None:
        anth = type("APIError", (Exception,), {"__module__": "anthropic._exceptions"})
        oai = type("APIError", (Exception,), {"__module__": "openai._exceptions"})
        cart = type("Err", (Exception,), {"__module__": "cartesia.tts"})
        assert _provider_for_exception(anth()) == "anthropic"
        assert _provider_for_exception(oai()) == "openai"
        assert _provider_for_exception(cart()) == "cartesia"
        assert _provider_for_exception(ValueError()) == "unknown"


class TestRequireCloudSecrets:
    def _cfg(self, **kw: str) -> SimpleNamespace:
        base = {
            "anthropic_api_key": "a",
            "openai_api_key": "o",
            "cartesia_api_key": "c",
            "cartesia_voice_id": "v",
        }
        base.update(kw)
        return SimpleNamespace(**base)

    def test_all_present_passes(self) -> None:
        require_cloud_secrets(self._cfg())  # no raise

    def test_missing_named_in_error(self) -> None:
        with pytest.raises(RuntimeError) as exc:
            require_cloud_secrets(self._cfg(openai_api_key="", cartesia_voice_id=""))
        msg = str(exc.value)
        assert "OPENAI_API_KEY" in msg and "CARTESIA_VOICE_ID" in msg
        assert "ANTHROPIC_API_KEY" not in msg


def _fake_app() -> SimpleNamespace:
    state = SimpleNamespace(active_session=None, session_swap_lock=asyncio.Lock())
    return SimpleNamespace(state=state)


def _session(sid: str) -> ActiveSession:
    return ActiveSession(session_id=sid, task=MagicMock(), websocket=MagicMock())


class TestSingleSessionSwap:
    async def test_install_returns_incumbent(self) -> None:
        app = _fake_app()
        a = _session("a")
        assert await _install_active(app, a) is None
        assert app.state.active_session is a
        b = _session("b")
        assert await _install_active(app, b) is a  # b displaces a
        assert app.state.active_session is b

    async def test_clear_is_identity_guarded(self) -> None:
        app = _fake_app()
        a, b = _session("a"), _session("b")
        await _install_active(app, a)
        await _install_active(app, b)  # active is now b
        # a's teardown must NOT null b's registration.
        await _clear_active(app, a)
        assert app.state.active_session is b
        # b's own teardown clears it.
        await _clear_active(app, b)
        assert app.state.active_session is None

    async def test_evict_cancels_and_closes(self) -> None:
        incumbent = ActiveSession(
            session_id="old",
            task=MagicMock(cancel=AsyncMock()),
            websocket=MagicMock(close=AsyncMock()),
        )
        await _evict(incumbent)
        incumbent.task.cancel.assert_awaited_once()
        incumbent.websocket.close.assert_awaited_once()
