"""La Libreta → Habla durable speaking-session handoffs (spec #033).

Two trust boundaries meet in this module and the whole point is that they never
touch:

- `POST /api/sessions` is **server-to-server**. It is gated by
  `LA_LIBRETA_API_TOKEN`, and holding that token buys exactly one thing: the
  right to create a handoff row. It cannot open a microphone, start a paid
  provider socket, or read a learner's progress.
- `GET /api/sessions/{id}` and `POST /api/sessions/{id}/complete` are the
  **learner's** browser, gated by the #016 shared secret like every other
  `/api` surface. The integration token is never sent to the browser and would
  be rejected here if it were.

Kept out of `api/routes/session.py` (the live WebSocket) so that separation is
structural rather than a convention someone has to remember.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import date, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api.routes.learner import require_api_token
from hable_ya.handoff import repo
from hable_ya.handoff.callback import (
    CallbackPolicyError,
    deliver_callback,
    validate_callback_url,
)
from hable_ya.handoff.models import SpeakingHandoff

logger = logging.getLogger("hable_ya.api.external_sessions")
router = APIRouter(prefix="/api/sessions")


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    return value if scheme.lower() == "bearer" and value else None


def require_la_libreta_token(request: Request) -> None:
    """Gate the integration surface on its own secret, in constant time.

    Fail-closed: an unset `la_libreta_api_token` rejects everything rather than
    waving it through, so a deployment that forgot to configure the integration
    does not accidentally publish an open session-creation endpoint. Neither
    the response nor the log reveals the expected value.
    """
    expected = request.app.state.settings.la_libreta_api_token
    presented = _bearer(request)
    if (
        not expected
        or presented is None
        or not secrets.compare_digest(presented, expected)
    ):
        logger.warning("create session: unauthorized integration request refused")
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


class SessionCreate(BaseModel):
    """The upstream request body.

    `extra="ignore"` is forward compatibility in the direction the contract
    asks for: La Libreta may add top-level fields without coordinating a Habla
    release. Known fields stay strict, and the two enums reject unknown values
    rather than mapping them to a fallback — silently downgrading `mode:
    "writing"` to a speaking session would be worse than a `400`.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source: Literal["la-libreta"]
    source_ref: str = Field(alias="sourceRef", min_length=1, max_length=200)
    mode: Literal["speaking"]
    text: str = Field(min_length=1, max_length=20_000)
    structures: list[str] = Field(max_length=100)
    target: str = Field(min_length=1, max_length=1_000)
    date: date
    callback_url: str | None = Field(default=None, alias="callbackUrl")


class SessionCreated(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    url: str
    created_at: datetime = Field(alias="createdAt")


class SessionHandoff(BaseModel):
    """What the learner's browser is allowed to see.

    Deliberately not the whole row: `callback_url` and the callback delivery
    state are operator/integration concerns, and the browser has no use for
    them.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    source_ref: str = Field(alias="sourceRef")
    mode: str
    text: str
    structures: list[str]
    target: str
    date: date
    created_at: datetime = Field(alias="createdAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")


def _view(handoff: SpeakingHandoff) -> SessionHandoff:
    return SessionHandoff(
        id=handoff.id,
        source=handoff.source,
        sourceRef=handoff.source_ref,
        mode=handoff.mode,
        text=handoff.text,
        structures=handoff.structures,
        target=handoff.target,
        date=handoff.date,
        createdAt=handoff.created_at,
        completedAt=handoff.completed_at,
    )


def _public_url(settings: Any, handoff_id: str) -> str:
    """Build the browser URL from configured origin only.

    Never from `Host` or `X-Forwarded-*`: those are attacker-controlled on a
    server-to-server endpoint, and this URL is what La Libreta redirects a
    person's browser to.
    """
    base = str(settings.public_base_url).strip()
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        logger.error("create session: public_base_url is not configured")
        raise HTTPException(status_code=503, detail="public base URL not configured")
    return f"{parsed.scheme}://{parsed.netloc}/session/{handoff_id}"


async def _parse_body(request: Request) -> SessionCreate:
    """Validate the body, answering `400` — not FastAPI's default `422`.

    The upstream contract names `400` for an invalid body or an unsupported
    enum value, and this endpoint's job is to implement that contract exactly.
    Parsing by hand rather than as a typed parameter keeps the status override
    scoped to this route: an app-level handler for `RequestValidationError`
    would have changed `/api/learner`'s answers too.
    """
    raw = await request.body()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="body is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    try:
        return SessionCreate.model_validate(parsed)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first.get("loc", ())) or "body"
        raise HTTPException(
            status_code=400, detail=f"{field}: {first.get('msg', 'invalid')}"
        ) from None


def _mismatch(body: SessionCreate, existing: SpeakingHandoff) -> list[str]:
    """Which non-key fields a replay disagrees with the stored row about."""
    fields = {
        "text": (body.text, existing.text),
        "structures": (body.structures, existing.structures),
        "target": (body.target, existing.target),
        "callbackUrl": (body.callback_url, existing.callback_url),
    }
    return [name for name, (new, old) in fields.items() if new != old]


@router.post(
    "",
    response_model=SessionCreated,
    response_model_by_alias=True,
    dependencies=[Depends(require_la_libreta_token)],
)
async def create_session(request: Request, response: Response) -> SessionCreated:
    """Create once per `(source, sourceRef, date)`; on replay the first wins.

    `201` for a new handoff, `200` for a replay, identical bodies. The stored
    payload is never mutated by a replay: an existing deep link must not change
    meaning under a learner who already has it open, and the alternative —
    rejecting a mismatch — would break the upstream requirement to return the
    existing session. A mismatch is logged instead, by field name only.
    """
    body = await _parse_body(request)
    settings = request.app.state.settings

    callback_url: str | None = None
    if body.callback_url is not None:
        try:
            callback_url = validate_callback_url(
                body.callback_url, settings.callback_origins
            )
        except CallbackPolicyError as exc:
            # Rejected before any row is written, so an unapproved destination
            # can never sit in the database waiting to be fetched.
            raise HTTPException(status_code=400, detail=f"callbackUrl: {exc}") from None

    async with _pool(request).acquire() as conn:
        handoff, created = await repo.insert_or_get(
            conn,
            handoff_id=f"sess_{uuid.uuid4().hex}",
            source=body.source,
            source_ref=body.source_ref,
            source_date=body.date,
            mode=body.mode,
            text=body.text,
            structures=body.structures,
            target=body.target,
            callback_url=callback_url,
        )

    if not created:
        differing = _mismatch(body, handoff)
        if differing:
            logger.warning(
                "handoff %s: replay for %s/%s differs in %s — keeping stored payload",
                handoff.id,
                handoff.source_ref,
                handoff.date.isoformat(),
                ", ".join(differing),
            )

    response.status_code = 201 if created else 200
    return SessionCreated(
        id=handoff.id,
        url=_public_url(settings, handoff.id),
        createdAt=handoff.created_at,
    )


@router.get(
    "/{handoff_id}",
    response_model=SessionHandoff,
    response_model_by_alias=True,
    dependencies=[Depends(require_api_token)],
)
async def get_session(request: Request, handoff_id: str) -> SessionHandoff:
    """Resolve a deep link for the learner's browser.

    Read-only and side-effect free — opening or reloading `/session/:id` must
    not start anything. `started_at` is stamped by the WebSocket handler when
    the learner actually presses start.
    """
    async with _pool(request).acquire() as conn:
        handoff = await repo.get(conn, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="session not found")
    return _view(handoff)


@router.post(
    "/{handoff_id}/complete",
    response_model=SessionHandoff,
    response_model_by_alias=True,
    dependencies=[Depends(require_api_token)],
)
async def complete_session(
    request: Request, handoff_id: str, background: BackgroundTasks
) -> SessionHandoff:
    """The explicit completion action (spec Open Question 1).

    Deliberately *not* wired to socket teardown. A disconnect, an error, an
    idle timeout, and a preemption all end a session, and none of them means
    the learner finished the task — reporting practice on any of those would
    over-report to La Libreta's activity tracking.

    Completion commits locally first; the callback is queued as a background
    task so a slow or dead La Libreta cannot delay or fail the learner's
    action.
    """
    async with _pool(request).acquire() as conn:
        handoff, transitioned = await repo.mark_completed(conn, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="session not found")

    # Only the transition fires a callback. A second completion — double click,
    # reconnect, a second tab — returns the same state and sends nothing.
    if transitioned and handoff.callback_url is not None:
        background.add_task(_run_callback, request.app, handoff)
    return _view(handoff)


async def _run_callback(app: Any, handoff: SpeakingHandoff) -> None:
    """Deliver and record. Isolated so a failure can never reach the learner."""
    settings = app.state.settings
    try:
        result = await deliver_callback(
            handoff,
            token=settings.la_libreta_api_token,
            allowed_origins=settings.callback_origins,
            timeout=settings.callback_timeout_seconds,
        )
        pool = getattr(app.state, "db_pool", None)
        if pool is None:
            return
        async with pool.acquire() as conn:
            await repo.record_callback_attempt(
                conn,
                handoff.id,
                attempts=result.attempts,
                delivered=result.delivered,
                error=result.error,
            )
    except Exception:
        logger.exception("handoff %s: callback delivery crashed", handoff.id)
