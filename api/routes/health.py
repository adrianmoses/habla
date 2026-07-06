"""Readiness probe.

Reports `ok` only when the app is warm, the DB is live, AND no cloud provider
has failed recently — so a `200 ok` means a session can actually run, not just
that the process is up (spec #016).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

# A provider that errored within this window marks the app degraded; it clears
# once no new error arrives for the window (transient blips self-heal; a revoked
# key keeps failing and stays degraded).
PROVIDER_ERROR_WINDOW_SECS = 60.0


def _recent_provider_errors(request: Request) -> list[str]:
    errors = getattr(request.app.state, "provider_errors", None)
    if not errors:
        return []
    now = time.monotonic()
    return [
        provider
        for provider, ts in errors.items()
        if now - ts < PROVIDER_ERROR_WINDOW_SECS
    ]


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    backend = settings.llm_model_name

    if not request.app.state.ready:
        return JSONResponse(
            status_code=503,
            content={"status": "warming_up", "llm_backend": backend},
        )

    db = getattr(request.app.state, "db", None)
    if db is None or not await db.ping():
        return JSONResponse(
            status_code=503,
            content={"status": "db_unreachable", "llm_backend": backend},
        )

    degraded = _recent_provider_errors(request)
    if degraded:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "llm_backend": backend,
                "providers": degraded,
            },
        )

    return JSONResponse(content={"status": "ok", "llm_backend": backend})
