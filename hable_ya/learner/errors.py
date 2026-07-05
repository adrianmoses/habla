"""ErrorRepo — per-turn error observation writes and category aggregates.

Writes go through two tables: `error_observations` (one row per distinct
error in a turn, immutable event log) and `error_counts` (one row per
category, incrementing counter with `last_seen_at`). Reads power the
top-N `error_patterns` list the prompt builder consumes.

All methods accept an `asyncpg.Connection` so the caller (the ingest
service) can compose them inside a shared transaction with `turns`,
vocabulary, and the AGE graph writes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class ErrorRepo:
    @staticmethod
    async def record(
        conn: asyncpg.Connection,
        *,
        turn_id: int,
        errors: list[dict[str, Any]],
        at: datetime,
    ) -> list[str]:
        """Insert one row per error + upsert `error_counts`.

        Returns the list of distinct categories touched (useful for the graph
        writer that follows in the same transaction).
        """
        if not errors:
            return []
        categories: list[str] = []
        for err in errors:
            category = str(err.get("type", "")).strip()
            if not category:
                continue
            produced = str(err.get("produced_form") or err.get("form") or "")
            target = str(err.get("target_form") or err.get("correction") or "")
            await conn.execute(
                """
                INSERT INTO error_observations
                    (turn_id, category, produced_form, target_form)
                VALUES ($1, $2, $3, $4)
                """,
                turn_id,
                category,
                produced,
                target,
            )
            categories.append(category)

        for category in set(categories):
            await conn.execute(
                """
                INSERT INTO error_counts (category, count, last_seen_at)
                VALUES ($1, 1, $2)
                ON CONFLICT (category) DO UPDATE
                SET count = error_counts.count + 1,
                    last_seen_at = EXCLUDED.last_seen_at
                """,
                category,
                at,
            )
        return categories

    @staticmethod
    async def top_categories(conn: asyncpg.Connection, *, limit: int = 3) -> list[str]:
        rows = await conn.fetch(
            """
            SELECT category FROM error_counts
            ORDER BY count DESC, last_seen_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [r["category"] for r in rows]
