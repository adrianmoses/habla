"""Shared-secret authorization for the public HTTP/WS surface (spec #016).

A single shared secret (`session_auth_token`) gates both the `/ws/session`
WebSocket (spec #016) and the `/api/learner*` read endpoints (spec #019). The
comparison lives here so the two call sites can't drift: same fail-closed
posture, same constant-time compare, same `session_auth_disabled` dev opt-out.
"""

from __future__ import annotations

import secrets

from hable_ya.config import Settings


def authorize_token(settings: Settings, presented: str | None) -> bool:
    """True iff `presented` is the configured shared secret.

    Fail-closed: if no secret is configured and auth is not explicitly
    disabled, every request is refused. `session_auth_disabled` is the local
    dev opt-out (mirrors `dev_endpoints_enabled`).
    """
    if settings.session_auth_disabled:
        return True
    if not settings.session_auth_token:
        return False  # fail-closed: no secret configured
    return presented is not None and secrets.compare_digest(
        presented, settings.session_auth_token
    )
