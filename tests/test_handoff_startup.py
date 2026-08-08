"""Fail-closed configuration and WebSocket handoff resolution (spec #033).

Two boundaries that are easy to get subtly wrong and hard to notice:

- Startup. A missing integration secret already fails closed at request time
  (`401`), but silently — La Libreta would see rejections with nothing on the
  Habla side to explain them. `require_integration_config` turns that into a
  boot error, and the explicit dev opt-out is what keeps a laptop working.
- The WebSocket. `?handoff=` is the only thing the browser sends, and it must
  be resolved server-side, after auth, into the authoritative payload.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from api.main import require_integration_config
from api.routes.session import _resolve_handoff
from hable_ya.config import Settings
from hable_ya.handoff.models import SpeakingHandoff


def _cfg(**kw: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "la_libreta_integration_disabled": False,
        "la_libreta_api_token": "la-libreta-secret",
        "public_base_url": "https://habla.example.com",
    }
    base.update(kw)
    return SimpleNamespace(**base)


class TestRequireIntegrationConfig:
    def test_fully_configured_passes(self) -> None:
        require_integration_config(_cfg())  # type: ignore[arg-type]

    def test_dev_opt_out_bypasses_the_check(self) -> None:
        require_integration_config(
            _cfg(  # type: ignore[arg-type]
                la_libreta_integration_disabled=True,
                la_libreta_api_token="",
                public_base_url="",
            )
        )

    def test_missing_token_refuses_to_boot(self) -> None:
        with pytest.raises(RuntimeError) as exc:
            require_integration_config(_cfg(la_libreta_api_token=""))  # type: ignore[arg-type]
        assert "LA_LIBRETA_API_TOKEN" in str(exc.value)
        # The error must point at the opt-out, or the only obvious fix is to
        # invent a token — which would silently publish the endpoint.
        assert "DISABLED" in str(exc.value)

    def test_missing_public_base_url_refuses_to_boot(self) -> None:
        with pytest.raises(RuntimeError) as exc:
            require_integration_config(_cfg(public_base_url=""))  # type: ignore[arg-type]
        assert "HABLE_YA_PUBLIC_BASE_URL" in str(exc.value)

    def test_an_unset_token_is_not_the_opt_out(self) -> None:
        # The distinction the whole check exists for: "I did not configure this"
        # must not read the same as "I chose not to run it".
        with pytest.raises(RuntimeError):
            require_integration_config(
                _cfg(la_libreta_api_token="", public_base_url="")  # type: ignore[arg-type]
            )


class TestSettingsDefaults:
    def test_keyless_settings_still_constructs(self) -> None:
        cfg = Settings()
        assert cfg.la_libreta_api_token == ""
        assert cfg.public_base_url == ""
        # Fail-closed defaults: no callback destination is permitted until the
        # operator names one, and the integration is on unless opted out.
        assert cfg.callback_origins == ()
        assert cfg.la_libreta_integration_disabled is False

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", ()),
            ("https://a.example.com", ("https://a.example.com",)),
            (
                " https://a.example.com , https://b.example.com/ ",
                ("https://a.example.com", "https://b.example.com"),
            ),
            ("HTTPS://A.EXAMPLE.COM", ("https://a.example.com",)),
            (" , ,", ()),
        ],
    )
    def test_callback_origins_parsing(
        self, raw: str, expected: tuple[str, ...]
    ) -> None:
        assert Settings(la_libreta_callback_origins=raw).callback_origins == expected


class _Acquire:
    def __init__(self, conn: object) -> None:
        self.conn = conn

    async def __aenter__(self) -> object:
        return self.conn

    async def __aexit__(self, *args: object) -> None:
        return None


class FakePool:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.queries: list[str] = []

    def acquire(self) -> _Acquire:
        return _Acquire(self)

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        self.queries.append(query)
        return self.row


class BrokenPool:
    def acquire(self) -> _Acquire:
        raise RuntimeError("pool is gone")


ROW = {
    "id": "sess_abc",
    "source": "la-libreta",
    "source_ref": "p02",
    "source_date": date(2026, 5, 2),
    "mode": "speaking",
    "prompt_text": "Describe una decisión.",
    "structures": '["condicional compuesto"]',
    "target": "monólogo de 3 minutos",
    "callback_url": None,
    "created_at": datetime(2026, 5, 2, 7, 14, 22, tzinfo=UTC),
    "started_at": None,
    "completed_at": None,
    "callback_attempts": 0,
    "callback_delivered_at": None,
}


class TestResolveHandoff:
    async def test_resolves_the_authoritative_payload_from_the_id(self) -> None:
        pool = FakePool(ROW)
        handoff = await _resolve_handoff(pool, "sess_abc")

        assert isinstance(handoff, SpeakingHandoff)
        # The prompt comes from the row, not from anything the browser sent.
        assert handoff.text == "Describe una decisión."
        assert handoff.structures == ["condicional compuesto"]

    async def test_no_handoff_param_is_an_ordinary_session(self) -> None:
        pool = FakePool(ROW)
        assert await _resolve_handoff(pool, None) is None
        assert await _resolve_handoff(pool, "") is None
        assert pool.queries == []

    async def test_an_unknown_id_degrades_to_an_ordinary_session(self) -> None:
        # Fail-safe like the #023 config parser: the pre-session view is where
        # a bad id gets reported, and breaking the handshake here would turn a
        # stale link into a connection error instead.
        assert await _resolve_handoff(FakePool(None), "sess_gone") is None

    async def test_a_lookup_failure_does_not_break_the_handshake(self) -> None:
        assert await _resolve_handoff(BrokenPool(), "sess_abc") is None

    async def test_no_pool_is_survivable(self) -> None:
        assert await _resolve_handoff(None, "sess_abc") is None
