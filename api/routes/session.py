"""Voice session WebSocket endpoint.

One WS connection → one Pipecat PipelineTask. The shared services (STT/LLM/
TTS) and the app-wide observation sink come from `app.state` (loaded in
lifespan); per-session state (transport, LLM context, aggregators, custom
processors) is built fresh inside the handler.

Connection is refused with code 1013 ("try again later") if the app is still
warming up, so clients don't wait indefinitely on a dead pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, WebSocket
from pipecat.pipeline.base_task import PipelineTaskParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from hable_ya.pipeline.prompts.builder import build_session_prompt
from hable_ya.pipeline.runner import build_pipeline_task, default_learner
from hable_ya.pipeline.serializer import RawPCMSerializer

logger = logging.getLogger("hable_ya.api.session")
router = APIRouter()


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
    if not getattr(app.state, "ready", False):
        await websocket.close(code=1013, reason="warming up")
        return

    await websocket.accept()
    session_id = uuid.uuid4().hex[:12]
    logger.info("session %s: client connected", session_id)

    settings = app.state.settings
    services = app.state.services
    sink = app.state.observation_sink
    ingest = getattr(app.state, "ingest", None)
    pool = getattr(app.state, "db_pool", None)

    learner = default_learner(settings)
    # Resolve recent_domains from `sessions` (empty on first run); build the
    # system prompt against the live profile + cooldown-aware theme choice.
    # The fine-tuned Gemma is trained to emit plain-text `log_turn(...)` on its
    # own; HABLE_YA_TOOLS is not injected into the LLM — see
    # hable_ya/tools/schema.py for the documented payload shape.
    recent_domains = await _query_recent_theme_domains(pool) if pool is not None else []
    session_prompt = await build_session_prompt(
        learner, pool=pool, recent_domains=recent_domains
    )
    context = LLMContext(
        messages=[{"role": "system", "content": session_prompt.text}],
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

    task = build_pipeline_task(
        services,
        transport,
        context,
        settings,
        sink=sink,
        session_id=session_id,
        ingest=ingest,
    )

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
    except Exception:
        logger.exception("session %s: pipeline error", session_id)
    finally:
        logger.info("session %s: client disconnected", session_id)
        if ingest is not None:
            try:
                await ingest.end_session(session_id=session_id)
            except Exception:
                logger.exception("session %s: end_session failed", session_id)
