"""Callback destination policy and delivery behaviour (spec #033).

`callbackUrl` is the one place Habla fetches a URL an external caller supplied,
so these tests are as much about what does *not* happen — no request to a
rejected destination, no redirect followed, no second attempt after a `4xx` —
as about the happy path. Delivery runs against `httpx.MockTransport` so the
policy is exercised without the network deciding the outcome.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import httpx
import pytest

from hable_ya.handoff import callback as cb
from hable_ya.handoff.models import SpeakingHandoff

TOKEN = "la-libreta-secret"
ALLOWED = ("https://la-libreta.example.com",)
# A globally-routable literal: `getaddrinfo` answers it locally, so the
# delivery-time resolution check runs without touching DNS.
PUBLIC_IP_ORIGIN = "https://93.184.216.34"


def _handoff(**overrides: object) -> SpeakingHandoff:
    base = {
        "id": "sess_abc",
        "source": "la-libreta",
        "source_ref": "p02",
        "date": date(2026, 5, 2),
        "mode": "speaking",
        "text": "Describe una decisión.",
        "structures": ["condicional compuesto"],
        "target": "monólogo de 3 minutos",
        "created_at": datetime(2026, 5, 2, 7, 14, 22, tzinfo=UTC),
        "completed_at": datetime(2026, 5, 2, 7, 32, 11, tzinfo=UTC),
        "callback_url": f"{PUBLIC_IP_ORIGIN}/cb",
    }
    base.update(overrides)
    return SpeakingHandoff(**base)  # type: ignore[arg-type]


class Recorder:
    """A MockTransport handler that answers from a script and logs requests."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.responses.pop(0) if self.responses else httpx.Response(200)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _client(recorder: Recorder, *, follow_redirects: bool = False) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(recorder), follow_redirects=follow_redirects
    )


async def _deliver(
    recorder: Recorder,
    handoff: SpeakingHandoff | None = None,
    *,
    allowed: tuple[str, ...] = (PUBLIC_IP_ORIGIN,),
) -> cb.CallbackResult:
    async with _client(recorder) as client:
        return await cb.deliver_callback(
            handoff or _handoff(),
            token=TOKEN,
            allowed_origins=allowed,
            client=client,
        )


# --------------------------------------------------------------------------
# Destination policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://la-libreta.example.com/cb",
        "https://other.example.com/cb",
        "https://la-libreta.example.com.evil.net/cb",
        "https://user:pass@la-libreta.example.com/cb",
        "https://127.0.0.1/cb",
        "https://[::1]/cb",
        "https://169.254.169.254/latest/meta-data",
        "https://192.168.1.10/cb",
        "https://la-libreta.example.com:8443/cb",
        "ftp://la-libreta.example.com/cb",
        "https:///cb",
    ],
)
def test_rejected_destinations(url: str) -> None:
    with pytest.raises(cb.CallbackPolicyError):
        cb.validate_callback_url(url, ALLOWED)


@pytest.mark.parametrize(
    "url",
    [
        "https://la-libreta.example.com/api/companion-callback",
        "https://la-libreta.example.com:443/cb",
        "https://LA-LIBRETA.example.com/cb",
        "https://la-libreta.example.com/cb?token=irrelevant",
    ],
)
def test_accepted_destinations(url: str) -> None:
    assert cb.validate_callback_url(url, ALLOWED) == url


def test_empty_allowlist_permits_nothing() -> None:
    # The default posture. A URL arriving in the payload is not consent.
    with pytest.raises(cb.CallbackPolicyError):
        cb.validate_callback_url("https://la-libreta.example.com/cb", ())


def test_a_non_default_port_must_be_allowlisted_explicitly() -> None:
    allowed = ("https://la-libreta.example.com:8443",)
    assert cb.validate_callback_url("https://la-libreta.example.com:8443/cb", allowed)
    with pytest.raises(cb.CallbackPolicyError):
        cb.validate_callback_url("https://la-libreta.example.com/cb", allowed)


async def test_rebinding_to_a_private_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An allowlisted name that answers with a private address is not fetched.

    This is the gap the create-time check cannot close: the origin was approved
    when the row was written, and DNS is free to say something different by the
    time delivery runs.
    """

    async def fake_getaddrinfo(host: str, port: int) -> list[object]:
        return [(None, None, None, "", ("10.0.0.7", port))]

    monkeypatch.setattr(cb, "_getaddrinfo", fake_getaddrinfo)
    with pytest.raises(cb.CallbackPolicyError):
        await cb.resolve_public_addresses("la-libreta.example.com", 443)


async def test_a_split_horizon_answer_is_refused_not_filtered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Public *and* private answers: picking the public one would let the
    # connection race back to the private one.
    async def fake_getaddrinfo(host: str, port: int) -> list[object]:
        return [
            (None, None, None, "", ("93.184.216.34", port)),
            (None, None, None, "", ("127.0.0.1", port)),
        ]

    monkeypatch.setattr(cb, "_getaddrinfo", fake_getaddrinfo)
    with pytest.raises(cb.CallbackPolicyError):
        await cb.resolve_public_addresses("la-libreta.example.com", 443)


async def test_a_rejected_destination_is_never_requested() -> None:
    recorder = Recorder()
    result = await _deliver(
        recorder,
        _handoff(callback_url="https://evil.example.net/cb"),
        allowed=(PUBLIC_IP_ORIGIN,),
    )
    assert result == cb.CallbackResult(
        delivered=False, attempts=0, error="callbackUrl origin is not allowed"
    )
    assert recorder.requests == []


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------


async def test_absent_callback_url_does_nothing() -> None:
    recorder = Recorder()
    result = await _deliver(recorder, _handoff(callback_url=None))
    assert result == cb.CallbackResult(delivered=False, attempts=0)
    assert recorder.requests == []


async def test_success_sends_the_contract_payload_once() -> None:
    recorder = Recorder(httpx.Response(200))
    result = await _deliver(recorder)

    assert result == cb.CallbackResult(delivered=True, attempts=1)
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    import json

    assert json.loads(request.content) == {
        "source": "la-libreta",
        "sourceRef": "p02",
        "date": "2026-05-02",
        "modality": "speaking",
        "completedAt": "2026-05-02T07:32:11Z",
    }


async def test_a_5xx_is_retried_exactly_once() -> None:
    recorder = Recorder(httpx.Response(503), httpx.Response(503))
    result = await _deliver(recorder)

    assert result.delivered is False
    assert result.attempts == 2
    assert result.error == "http 503"


async def test_a_retry_after_a_5xx_can_succeed() -> None:
    recorder = Recorder(httpx.Response(500), httpx.Response(204))
    result = await _deliver(recorder)

    assert result == cb.CallbackResult(delivered=True, attempts=2)


async def test_a_4xx_is_not_retried() -> None:
    # A rejected payload will be rejected identically the second time; retrying
    # only doubles the noise on La Libreta's side.
    recorder = Recorder(httpx.Response(400), httpx.Response(200))
    result = await _deliver(recorder)

    assert result.delivered is False
    assert result.attempts == 1
    assert result.error == "http 400"
    assert len(recorder.requests) == 1


async def test_a_timeout_is_retried_once_then_reported() -> None:
    recorder = Recorder(
        httpx.ReadTimeout("timed out"), httpx.ConnectTimeout("timed out")
    )
    result = await _deliver(recorder)

    assert result.delivered is False
    assert result.attempts == 2
    assert result.error is not None and "ConnectTimeout" in result.error


async def test_a_transport_failure_is_retried_then_can_succeed() -> None:
    recorder = Recorder(httpx.ConnectError("refused"), httpx.Response(200))
    result = await _deliver(recorder)

    assert result == cb.CallbackResult(delivered=True, attempts=2)


async def test_a_redirect_is_not_followed() -> None:
    # Following one would step straight out of the allowlist — the destination
    # was approved, the redirect target never was.
    recorder = Recorder(
        httpx.Response(302, headers={"location": "https://127.0.0.1/cb"})
    )
    result = await _deliver(recorder)

    assert result.delivered is False
    assert result.error == "http 302"
    assert len(recorder.requests) == 1
    assert recorder.requests[0].url.host == "93.184.216.34"


async def test_delivery_never_raises_and_never_logs_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = Recorder(httpx.ConnectError("refused"), httpx.Response(500))
    with caplog.at_level(logging.DEBUG):
        result = await _deliver(recorder)

    assert result.delivered is False
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert TOKEN not in logged
    assert "sess_abc" in logged  # still diagnosable by handoff id


async def test_the_default_client_is_bounded_and_does_not_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no client injected, the one built here must carry the limits.

    Asserted rather than assumed: an unbounded outbound POST inside a
    background task is how a dead callback host turns into a leaked task per
    completed session.
    """
    captured: dict[str, object] = {}
    real = httpx.AsyncClient

    def spy(**kwargs: object) -> httpx.AsyncClient:
        captured.update(kwargs)
        return real(transport=httpx.MockTransport(Recorder(httpx.Response(200))))

    monkeypatch.setattr(cb.httpx, "AsyncClient", spy)
    result = await cb.deliver_callback(
        _handoff(), token=TOKEN, allowed_origins=(PUBLIC_IP_ORIGIN,), timeout=2.5
    )

    assert result.delivered is True
    assert captured["timeout"] == 2.5
    assert captured["follow_redirects"] is False
