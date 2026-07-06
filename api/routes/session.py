"""Voice session WebSocket endpoint.

One WS connection → one Pipecat PipelineTask. Per-session state — services
(STT/LLM/TTS), LLM context, aggregators, custom processors — is built fresh
inside the handler (spec #016), so concurrent connections cannot clobber each
other's `log_turn` routing on a shared service. The app-wide observation sink
comes from `app.state`.

Access control & single-session policy (spec #016):
- A shared-secret token gates the endpoint (fail-closed unless
  `session_auth_disabled`). Checked before `accept()` — no paid-API work runs
  for an unauthorized client.
- At most one active session: a new connection preempts the incumbent (newest
  wins), so a stale/half-open session can never block a new client. The swap is
  guarded by a lock held only for the pointer swap, never the session lifetime.
- Connection is refused with 1013 if the app is still warming up.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, WebSocket
from pipecat.pipeline.base_task import PipelineTaskParams
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from hable_ya.config import Settings
from hable_ya.pipeline.log_turn_handler import make_log_turn_handler
from hable_ya.pipeline.prompts.builder import build_session_prompt
from hable_ya.pipeline.runner import build_pipeline_task, default_learner
from hable_ya.pipeline.serializer import RawPCMSerializer
from hable_ya.pipeline.services import build_session_services
from hable_ya.tools.schema import HABLE_YA_TOOLS_SCHEMA, LOG_TURN_NAME

logger = logging.getLogger("hable_ya.api.session")
router = APIRouter()


@dataclass
class ActiveSession:
    """The one in-flight session; held on `app.state.active_session`."""

    session_id: str
    task: PipelineTask
    websocket: WebSocket


def _extract_token(websocket: WebSocket) -> tuple[str | None, str | None]:
    """Return (token, subprotocol_to_echo).

    Token may arrive as a `?token=` query param or as the first offered
    `Sec-WebSocket-Protocol` value. If via subprotocol, it must be echoed on
    accept for the browser handshake to complete.
    """
    token = websocket.query_params.get("token")
    if token is not None:
        return token, None
    proto = websocket.headers.get("sec-websocket-protocol")
    if proto:
        first = proto.split(",")[0].strip()
        return first, first
    return None, None


def _authorized(settings: Settings, presented: str | None) -> bool:
    if settings.session_auth_disabled:
        return True
    if not settings.session_auth_token:
        return False  # fail-closed: no secret configured
    return presented is not None and secrets.compare_digest(
        presented, settings.session_auth_token
    )


def _provider_for_exception(exc: BaseException) -> str:
    module = type(exc).__module__
    if module.startswith("anthropic"):
        return "anthropic"
    if module.startswith("openai"):
        return "openai"
    if "cartesia" in module:
        return "cartesia"
    return "unknown"


def _record_provider_error(app: object, exc: BaseException) -> None:
    """Best-effort: note which provider failed so `/health` can go degraded."""
    errors = getattr(app.state, "provider_errors", None)  # type: ignore[attr-defined]
    if errors is not None:
        errors[_provider_for_exception(exc)] = time.monotonic()


async def _install_active(app: object, this: ActiveSession) -> ActiveSession | None:
    """Swap `this` in as the active session; return the displaced incumbent.

    Holds the swap lock only for the pointer swap — never for a session's
    lifetime — so no long-held lock can go stale and brick the endpoint.
    """
    lock: asyncio.Lock = app.state.session_swap_lock  # type: ignore[attr-defined]
    async with lock:
        incumbent = app.state.active_session  # type: ignore[attr-defined]
        app.state.active_session = this  # type: ignore[attr-defined]
        return incumbent  # type: ignore[no-any-return]


async def _clear_active(app: object, this: ActiveSession) -> None:
    """Identity-guarded clear: only null `active_session` if it's still `this`,
    so an evicted session's teardown can't wipe its successor's registration."""
    lock: asyncio.Lock = app.state.session_swap_lock  # type: ignore[attr-defined]
    async with lock:
        if app.state.active_session is this:  # type: ignore[attr-defined]
            app.state.active_session = None  # type: ignore[attr-defined]


async def _evict(incumbent: ActiveSession) -> None:
    """Cancel an incumbent session's pipeline and close its socket."""
    try:
        await incumbent.task.cancel(reason="preempted")
    finally:
        try:
            await incumbent.websocket.close(code=1012, reason="preempted")
        except Exception:
            pass  # already closing / gone


async def _query_recent_theme_domains(pool: object, limit: int = 3) -> list[str]:
    async with pool.acquire() as conn:  # type: ignore[attr-defined]
        rows = await conn.fetch(
            "SELECT theme_domain FROM sessions "
            "WHERE theme_domain IS NOT NULL "
            "ORDER BY started_at DESC LIMIT $1",
            limit,
        )
    return [r["theme_domain"] for r in rows]


@router.websocket("/ws/session")
async def session_ws(websocket: WebSocket) -> None:
    app = websocket.app
    settings = app.state.settings

    if not getattr(app.state, "ready", False):
        await websocket.close(code=1013, reason="warming up")
        return

    # Auth gate — before accept() and before any DB / paid-API work.
    token, subprotocol = _extract_token(websocket)
    if not _authorized(settings, token):
        # Never log the token itself.
        logger.warning("session: unauthorized connection refused")
        await websocket.close(code=1008, reason="unauthorized")
        return

    await websocket.accept(subprotocol=subprotocol)
    session_id = uuid.uuid4().hex[:12]
    logger.info("session %s: client connected", session_id)

    services = build_session_services(settings)  # per-session isolation (#016)
    sink = app.state.observation_sink
    ingest = getattr(app.state, "ingest", None)
    pool = getattr(app.state, "db_pool", None)

    learner = default_learner(settings)
    # Resolve recent_domains from `sessions` (empty on first run); build the
    # system prompt against the live profile + cooldown-aware theme choice.
    recent_domains = await _query_recent_theme_domains(pool) if pool is not None else []
    session_prompt = await build_session_prompt(
        learner, pool=pool, recent_domains=recent_domains
    )
    # Register `log_turn` with the model (native tool-calling) on THIS session's
    # own LLM service, so a concurrent connection cannot overwrite the handler.
    context = LLMContext(
        messages=[{"role": "system", "content": session_prompt.text}],
        tools=HABLE_YA_TOOLS_SCHEMA,
    )
    services.llm.register_function(
        LOG_TURN_NAME, make_log_turn_handler(sink, session_id, ingest=ingest)
    )

    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            serializer=RawPCMSerializer(settings.audio_sample_rate),
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=settings.audio_sample_rate,
            audio_out_sample_rate=settings.audio_sample_rate,
            audio_in_channels=1,
            audio_out_channels=1,
        ),
    )

    task = build_pipeline_task(services, transport, context, settings, sink=sink)
    this = ActiveSession(session_id=session_id, task=task, websocket=websocket)

    # Preemptive single-session cap: install as active (lock held only for the
    # swap), then evict the incumbent outside the lock. Newest wins → a stale
    # session can never block a new client.
    incumbent = await _install_active(app, this)
    if incumbent is not None:
        logger.info(
            "session %s: preempting incumbent %s", session_id, incumbent.session_id
        )
        await _evict(incumbent)

    if ingest is not None:
        try:
            await ingest.start_session(
                session_id=session_id,
                theme_domain=session_prompt.theme.domain,
                band=session_prompt.band,
            )
        except Exception:
            logger.exception(
                "session %s: start_session failed — continuing without DB state",
                session_id,
            )

    try:
        await task.run(params=PipelineTaskParams(loop=asyncio.get_event_loop()))
    except Exception as exc:
        _record_provider_error(app, exc)
        logger.exception("session %s: pipeline error", session_id)
    finally:
        logger.info("session %s: client disconnected", session_id)
        await _clear_active(app, this)
        if ingest is not None:
            try:
                await ingest.end_session(session_id=session_id)
            except Exception:
                logger.exception("session %s: end_session failed", session_id)
