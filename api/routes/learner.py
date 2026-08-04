"""Production learner-progress API (spec #019, extended by #021).

Authenticated HTTP endpoints exposing the learner state that the runtime
already writes every turn — so the `web/` SPA (#020) can finally surface band,
session history, and progression. Mounted unconditionally (unlike the dev-gated
`/dev/learner`) and gated by the #016 shared secret via an `Authorization:
Bearer` header.

The `PATCH` added by #021 is the first *write* on this surface. It carries no
CSRF risk — the credential is a header token, not a cookie — and it is not an
escalation of what the shared secret grants: a holder could already open
`/ws/session` and spend on the metered APIs.

Single-tenant: there is one learner (`learner_profile.id = 1`), so no path
parameter identifies whose progress this is. That is a decided non-goal, not an
oversight — see spec #021 Key Decision 4 for what reversing it would cost.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from hable_ya.auth import authorize_token
from hable_ya.learner import read
from hable_ya.learner.identity import (
    InvalidDisplayName,
    normalize_display_name,
    set_display_name,
)

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


class ProfileUpdate(BaseModel):
    """The mutable part of the learner profile — one field, for now.

    `max_length` here is only an outer guard against buffering something
    absurd. The product rule is 40 characters *after* trimming and lives in
    `normalize_display_name`, so `"  Ana  "` is valid and the bound is
    unit-testable without going through HTTP.
    """

    display_name: str | None = Field(default=None, max_length=200)


@router.get("", dependencies=[Depends(require_api_token)])
async def get_learner(request: Request) -> dict[str, Any]:
    return await read.profile_payload(_pool(request))


@router.patch("", dependencies=[Depends(require_api_token)])
async def patch_learner(request: Request, body: ProfileUpdate) -> dict[str, Any]:
    """Set or clear the learner's display name.

    `null` and any all-whitespace string clear it back to SQL NULL. An empty
    body is rejected rather than treated as a clear — with one mutable field,
    `{}` is far more likely to be a mistake than an intent to wipe the name.

    Validation runs before the write, so a rejected request never persists a
    partially-validated value. The updated name comes back so the client can
    render without a refetch.
    """
    if "display_name" not in body.model_fields_set:
        raise HTTPException(status_code=422, detail="display_name is required")
    try:
        value = normalize_display_name(body.display_name)
    except InvalidDisplayName as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await set_display_name(_pool(request), value)
    return {"display_name": value}


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
