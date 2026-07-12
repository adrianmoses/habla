"""FastAPI app for hable-ya.

Loads the shared Pipecat services (STT / LLM / TTS) once during lifespan and
confirms the Anthropic API is reachable before flipping
`app.state.ready = True`. All three models are managed APIs (Claude / OpenAI /
Cartesia), so the app runs CPU-only — no CUDA bootstrap needed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI

from api.routes.health import router as health_router
from api.routes.learner import router as learner_router
from api.routes.session import router as session_router
from hable_ya.config import Settings, settings
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

_REQUIRED_SECRETS = (
    ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    ("OPENAI_API_KEY", "openai_api_key"),
    ("CARTESIA_API_KEY", "cartesia_api_key"),
    ("CARTESIA_VOICE_ID", "cartesia_voice_id"),
)


def require_cloud_secrets(cfg: Settings) -> None:
    """Fail fast at startup on any missing cloud credential (spec #016).

    Turns a first-turn crash (bad OpenAI/Cartesia config passing startup) into a
    boot-time error. Not a `Settings` validator — tests construct `Settings()`
    with no keys and must keep working; this runs only on the serving path.
    """
    missing = [env for env, attr in _REQUIRED_SECRETS if not getattr(cfg, attr)]
    if missing:
        raise RuntimeError(
            f"Missing required cloud credentials: {', '.join(missing)}. "
            "Set them in the environment / .env before starting."
        )


# The placeholder DB password baked into the default DSN + the docker-compose
# dev defaults. Safe locally; a boot-time error in production.
_PLACEHOLDER_DB_PASSWORD = "hable_ya"


def require_secure_db_credentials(cfg: Settings) -> None:
    """Fail fast on an empty or placeholder DB password (spec #017).

    Defense-in-depth behind the prod compose's `${POSTGRES_PASSWORD:?}` gate: if
    the app is ever started with the shipped `hable_ya:hable_ya` default (or a
    passwordless DSN), refuse to boot. `allow_default_db_credentials` is the dev
    opt-out (base compose sets it true); the prod overlay leaves it false. Like
    `require_cloud_secrets`, this lives on the serving path, not in a `Settings`
    validator, so keyless CI `Settings()` construction is unaffected.
    """
    if cfg.allow_default_db_credentials:
        return
    password = urlsplit(cfg.database_url).password
    if not password or password == _PLACEHOLDER_DB_PASSWORD:
        raise RuntimeError(
            "Insecure database credentials: the DB password is empty or the "
            f"placeholder '{_PLACEHOLDER_DB_PASSWORD}'. Inject a real "
            "POSTGRES_PASSWORD, or set HABLE_YA_ALLOW_DEFAULT_DB_CREDENTIALS=true "
            "for local development."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.ready = False
    app.state.settings = settings
    require_cloud_secrets(settings)
    require_secure_db_credentials(settings)
    if not settings.session_auth_token and not settings.session_auth_disabled:
        logger.error(
            "HABLE_YA_SESSION_AUTH_TOKEN is unset and session_auth_disabled is "
            "False — /ws/session will refuse all connections (fail-closed)."
        )
    # Single-session enforcement + reactive-health state (spec #016).
    app.state.active_session = None
    app.state.session_swap_lock = asyncio.Lock()
    app.state.provider_errors = {}
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
app.include_router(learner_router)

if settings.dev_endpoints_enabled:
    from api.routes.dev import router as dev_router  # noqa: E402

    logger.warning("Dev endpoints enabled — do not use in production")
    app.include_router(dev_router)
