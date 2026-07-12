"""Production learner-progress read API (spec #019).

Authenticated, read-only HTTP endpoints exposing the learner state that the
runtime already writes every turn — so the `web/` SPA (#020) can finally
surface band, session history, and progression. Mounted unconditionally (unlike
the dev-gated `/dev/learner`) and gated by the #016 shared secret via an
`Authorization: Bearer` header.

Single-tenant: there is one learner (`learner_profile.id = 1`), so no path
parameter identifies whose progress this is.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from hable_ya.auth import authorize_token
from hable_ya.learner import read

router = APIRouter(prefix="/api/learner")


def require_api_token(request: Request) -> None:
    """Reject unless a valid shared secret arrives as `Authorization: Bearer`.

    Fail-closed, sharing `hable_ya.auth.authorize_token` with the WS gate. The
    token is never logged or echoed.
    """
    header = request.headers.get("authorization")
    presented: str | None = None
    if header is not None:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value:
            presented = value
    if not authorize_token(request.app.state.settings, presented):
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _pool(request: Request) -> Any:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db pool not ready")
    return pool


@router.get("", dependencies=[Depends(require_api_token)])
async def get_learner(request: Request) -> dict[str, Any]:
    return await read.profile_payload(_pool(request))


@router.get("/sessions", dependencies=[Depends(require_api_token)])
async def get_sessions(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    sessions = await read.session_history(_pool(request), limit=limit, offset=offset)
    return {"sessions": sessions, "limit": limit, "offset": offset}


@router.get("/band-history", dependencies=[Depends(require_api_token)])
async def get_band_history(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    return {"band_history": await read.band_history(_pool(request), limit=limit)}
