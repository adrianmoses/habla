"""Async wrapper around `alembic.command.upgrade`."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def _build_config() -> Config:
    return Config(str(_ALEMBIC_INI))


def _upgrade_sync(cfg: Config) -> None:
    command.upgrade(cfg, "head")


async def upgrade_to_head() -> None:
    # Run on a worker thread: env.py does asyncio.run(...) internally, which
    # would raise if called from a thread that already owns an event loop.
    # Retry absorbs the narrow cold-start window where pg_isready returns OK
    # but the catalog is still initializing.
    cfg = _build_config()
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(
            (asyncpg.CannotConnectNowError, ConnectionError, OSError)
        ),
        reraise=True,
    ):
        with attempt:
            logger.info("Running alembic upgrade head")
            await asyncio.to_thread(_upgrade_sync, cfg)
