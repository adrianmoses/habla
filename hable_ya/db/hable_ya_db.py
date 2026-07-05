"""Learner-facing DB access layer.

In this slice (spec 028) the class is a near-stub — only `ping()` is wired, for
the health endpoint. The real query layer lives in consumer specs.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

logger = logging.getLogger(__name__)


class HableYaDB:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ping(self) -> bool:
        try:
            value = await asyncio.wait_for(self._pool.fetchval("SELECT 1"), timeout=0.5)
        except (TimeoutError, asyncpg.PostgresError, OSError) as exc:
            logger.warning("DB ping failed: %s", exc)
            return False
        return bool(value == 1)
