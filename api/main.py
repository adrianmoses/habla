"""FastAPI app for hable-ya.

Loads the shared Pipecat services (STT / LLM / TTS) once during lifespan and
confirms the Anthropic API is reachable before flipping
`app.state.ready = True`. All three models are managed APIs (Claude / OpenAI /
Cartesia), so the app runs CPU-only — no CUDA bootstrap needed.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.health import router as health_router
from api.routes.session import router as session_router
from hable_ya.config import settings
from hable_ya.db import (
    HableYaDB,
    close_pool,
    open_pool,
    upgrade_to_head,
)
from hable_ya.learner import graph as learner_graph
from hable_ya.learner.ingest import TurnIngestService
from hable_ya.learner.leveling import LevelingService
from hable_ya.pipeline.services import load_services, warmup_llm
from hable_ya.runtime.observations import TurnObservationSink

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("hable_ya.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.ready = False
    app.state.settings = settings
    app.state.services = load_services(settings)
    app.state.observation_sink = TurnObservationSink(
        path=settings.runtime_turns_path,
        ring_size=settings.observation_ring_size,
    )
    logger.info(
        "Turn observations → %s (ring size %d)",
        settings.runtime_turns_path,
        settings.observation_ring_size,
    )
    await upgrade_to_head()
    app.state.db_pool = await open_pool()
    app.state.db = HableYaDB(app.state.db_pool)
    app.state.leveling = LevelingService(app.state.db_pool)
    app.state.ingest = TurnIngestService(
        app.state.db_pool,
        leveling=app.state.leveling,
        sink=app.state.observation_sink,
    )

    # Seed the single Learner node and one Scenario node per theme so the
    # first session's graph writes can MATCH them. Both calls are idempotent.
    async with app.state.db_pool.acquire() as conn:
        await learner_graph.ensure_learner_node(conn)
        await learner_graph.ensure_scenario_nodes(conn)

    try:
        await warmup_llm(settings)
        app.state.ready = True
        logger.info("hable-ya ready on %s:%d", settings.host, settings.port)
        yield
    finally:
        await close_pool(app.state.db_pool)


app = FastAPI(title="hable-ya", lifespan=lifespan)
app.include_router(health_router)
app.include_router(session_router)

if settings.dev_endpoints_enabled:
    from api.routes.dev import router as dev_router  # noqa: E402

    logger.warning("Dev endpoints enabled — do not use in production")
    app.include_router(dev_router)
