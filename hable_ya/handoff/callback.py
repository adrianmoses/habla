"""Outbound completion callback to La Libreta (spec #033).

This is the only place Habla fetches a URL that an external caller supplied, so
it is the only place with an SSRF surface. Two gates, deliberately at different
times:

1. **Create time** (:func:`validate_callback_url`). Structural policy — HTTPS,
   no credentials in the URL, and the origin must appear in an explicitly
   configured allowlist that defaults to *empty*. A malformed or unapproved
   destination is a `400` and no row is written, so a bad URL can never sit in
   the database waiting to be fetched later.
2. **Delivery time** (:func:`resolve_public_addresses`). The allowlisted
   hostname is resolved and every address it answers with must be globally
   routable, so a hijacked or rebound DNS record for an approved origin cannot
   point the request at loopback, a link-local metadata endpoint, or the
   private network the container sits on.

Delivery itself is best-effort and never blocks or reverses local completion:
one attempt, one retry after a `5xx` or a transport failure, no retry on `4xx`
(a rejected payload will be rejected again), bounded connect/read timeouts, and
redirects disabled — following one would leave the allowlist behind.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from hable_ya.handoff.models import SpeakingHandoff

logger = logging.getLogger("hable_ya.handoff.callback")

#: A 5xx or a transport failure gets exactly one more try; a 4xx gets none.
MAX_ATTEMPTS = 2


class CallbackPolicyError(ValueError):
    """A callback destination is not permitted. Message is caller-safe."""


def origin_of(url: str) -> str:
    """`scheme://host[:port]`, lowercased, with a default port dropped."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = parts.port
    scheme = parts.scheme.lower()
    if port is None or (scheme == "https" and port == 443):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _is_global(address: str) -> bool:
    """Whether an IP is routable on the public internet.

    `is_global` already excludes loopback, link-local (including the
    169.254.169.254 metadata address), private ranges, and the reserved and
    unspecified blocks — checking it is stricter than enumerating them, and
    stays correct as the IANA registries change.
    """
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def validate_callback_url(raw: str, allowed_origins: tuple[str, ...]) -> str:
    """Return `raw` if it is an approved callback destination, else raise.

    Fails closed on an empty allowlist: the operator has to name La Libreta's
    production origin before Habla will fetch anything at all.
    """
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https":
        raise CallbackPolicyError("callbackUrl must use https")
    if parts.username or parts.password:
        raise CallbackPolicyError("callbackUrl must not carry credentials")
    host = parts.hostname
    if not host:
        raise CallbackPolicyError("callbackUrl has no host")
    # An IP literal is judged directly — it never reaches DNS, so the
    # delivery-time resolution check below would never see it.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _is_global(host):
            raise CallbackPolicyError("callbackUrl host is not a public address")
    if not allowed_origins:
        raise CallbackPolicyError("no callback origin is configured")
    if origin_of(raw) not in allowed_origins:
        raise CallbackPolicyError("callbackUrl origin is not allowed")
    return raw


async def resolve_public_addresses(host: str, port: int) -> list[str]:
    """Resolve `host`, requiring every answer to be globally routable.

    Raises :class:`CallbackPolicyError` on a non-global answer rather than
    filtering it out: a name that resolves to *both* a public and a private
    address is the rebinding shape this check exists to stop, and picking the
    public one would let the connection race back to the private one.

    A narrow residual window remains — the socket resolves the name again when
    it connects — but crossing it requires control of an operator-configured
    zone, at which point the approved destination is already the attacker's.
    """
    loop_infos = await _getaddrinfo(host, port)
    addresses = [info[4][0] for info in loop_infos]
    if not addresses:
        raise CallbackPolicyError("callbackUrl host did not resolve")
    for address in addresses:
        if not _is_global(address):
            raise CallbackPolicyError(
                "callbackUrl host resolves to a non-public address"
            )
    return addresses


async def _getaddrinfo(host: str, port: int) -> list[Any]:
    loop = asyncio.get_running_loop()
    try:
        return list(
            await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        )
    except OSError as exc:
        raise CallbackPolicyError("callbackUrl host did not resolve") from exc


def callback_payload(handoff: SpeakingHandoff) -> dict[str, str]:
    """The exact wire body from the upstream contract."""
    completed_at = handoff.completed_at
    assert completed_at is not None, "callback requires a completed handoff"
    return {
        "source": handoff.source,
        "sourceRef": handoff.source_ref,
        "date": handoff.date.isoformat(),
        "modality": handoff.mode,
        "completedAt": completed_at.isoformat().replace("+00:00", "Z"),
    }


@dataclass(slots=True, frozen=True)
class CallbackResult:
    delivered: bool
    attempts: int
    error: str | None = None


async def deliver_callback(
    handoff: SpeakingHandoff,
    *,
    token: str,
    allowed_origins: tuple[str, ...],
    timeout: float = 5.0,
    client: httpx.AsyncClient | None = None,
) -> CallbackResult:
    """Attempt the completion callback. Never raises.

    Returns what happened so the caller can persist it. `client` is injectable
    so the callback policy can be tested against a fake transport rather than
    the network.
    """
    url = handoff.callback_url
    if url is None:
        return CallbackResult(delivered=False, attempts=0)

    try:
        validate_callback_url(url, allowed_origins)
        parts = urlsplit(url)
        await resolve_public_addresses(parts.hostname or "", parts.port or 443)
    except CallbackPolicyError as exc:
        # Logged by handoff id, never with the URL's query string or the token.
        logger.warning(
            "handoff %s: callback rejected by policy: %s", handoff.id, exc
        )
        return CallbackResult(delivered=False, attempts=0, error=str(exc))

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    payload = callback_payload(handoff)
    attempts = 0
    error: str | None = None
    try:
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            try:
                response = await http.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                # Transport failure — retryable, and the exception type is
                # enough to diagnose without echoing request contents.
                error = f"transport error: {type(exc).__name__}"
                logger.warning(
                    "handoff %s: callback attempt %d failed (%s)",
                    handoff.id,
                    attempts,
                    error,
                )
                continue
            if 200 <= response.status_code < 300:
                logger.info(
                    "handoff %s: callback delivered (%d) on attempt %d",
                    handoff.id,
                    response.status_code,
                    attempts,
                )
                return CallbackResult(delivered=True, attempts=attempts)
            error = f"http {response.status_code}"
            if response.status_code < 500:
                # A 4xx is a verdict on the payload, not a hiccup. Retrying
                # would re-send the identical body for the identical answer.
                logger.warning(
                    "handoff %s: callback rejected (%s) — not retrying",
                    handoff.id,
                    error,
                )
                return CallbackResult(delivered=False, attempts=attempts, error=error)
            logger.warning(
                "handoff %s: callback attempt %d failed (%s)",
                handoff.id,
                attempts,
                error,
            )
    finally:
        if owns_client:
            await http.aclose()

    return CallbackResult(delivered=False, attempts=attempts, error=error)
