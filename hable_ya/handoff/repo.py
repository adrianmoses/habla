"""Persistence for the handoff lifecycle (spec #033).

Every state change here is written as a *conditional* UPDATE whose WHERE clause
carries the precondition, and each returns whether it was the transition that
actually happened. That shape is what makes the lifecycle safe to retry: a
double-clicked completion, a reconnect, or two racing requests all resolve to
one winner in the database rather than in application code that would have to
hold a lock to be right.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from hable_ya.handoff.models import HANDOFF_COLUMNS, SpeakingHandoff, handoff_from_row

_TABLE = "external_session_handoffs"


async def insert_or_get(
    conn: Any,
    *,
    handoff_id: str,
    source: str,
    source_ref: str,
    source_date: date,
    mode: str,
    text: str,
    structures: list[str],
    target: str,
    callback_url: str | None,
) -> tuple[SpeakingHandoff, bool]:
    """Create the handoff, or return the one that already owns the key.

    Race-safe without a transaction or an advisory lock: `ON CONFLICT DO
    NOTHING` lets exactly one of two concurrent inserts win at the unique
    index, and the loser's follow-up SELECT reads the winner's row. Returns
    `(handoff, created)`.
    """
    row = await conn.fetchrow(
        f"""
        INSERT INTO {_TABLE}
            (id, source, source_ref, source_date, mode, prompt_text,
             structures, target, callback_url)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
        ON CONFLICT (source, source_ref, source_date) DO NOTHING
        RETURNING {HANDOFF_COLUMNS}
        """,
        handoff_id,
        source,
        source_ref,
        source_date,
        mode,
        text,
        json.dumps(structures),
        target,
        callback_url,
    )
    if row is not None:
        return handoff_from_row(row), True

    existing = await conn.fetchrow(
        f"""
        SELECT {HANDOFF_COLUMNS} FROM {_TABLE}
        WHERE source = $1 AND source_ref = $2 AND source_date = $3
        """,
        source,
        source_ref,
        source_date,
    )
    if existing is None:
        # The conflicting row disappeared between the insert and the select —
        # only reachable if something deleted it concurrently. Surfaced rather
        # than papered over with a retry loop.
        raise LookupError("handoff vanished between insert and select")
    return handoff_from_row(existing), False


async def get(conn: Any, handoff_id: str) -> SpeakingHandoff | None:
    row = await conn.fetchrow(
        f"SELECT {HANDOFF_COLUMNS} FROM {_TABLE} WHERE id = $1", handoff_id
    )
    return handoff_from_row(row) if row is not None else None


async def mark_started(conn: Any, handoff_id: str) -> None:
    """Stamp first-start. Later starts leave the original timestamp alone.

    A learner may open the deep link, close it, and come back; `started_at`
    answers "when did practice first begin", which a last-write-wins column
    could not.
    """
    await conn.execute(
        f"UPDATE {_TABLE} SET started_at = now() "
        "WHERE id = $1 AND started_at IS NULL",
        handoff_id,
    )


async def mark_completed(
    conn: Any, handoff_id: str
) -> tuple[SpeakingHandoff | None, bool]:
    """Complete the handoff once. Returns `(handoff, transitioned)`.

    `transitioned` is False for an unknown id *and* for a repeat completion —
    the caller uses it to decide whether to fire the callback, which is what
    keeps a double-click from producing two successful deliveries.
    """
    row = await conn.fetchrow(
        f"""
        UPDATE {_TABLE} SET completed_at = now()
        WHERE id = $1 AND completed_at IS NULL
        RETURNING {HANDOFF_COLUMNS}
        """,
        handoff_id,
    )
    if row is not None:
        return handoff_from_row(row), True
    return await get(conn, handoff_id), False


async def record_callback_attempt(
    conn: Any,
    handoff_id: str,
    *,
    attempts: int,
    delivered: bool,
    error: str | None,
) -> bool:
    """Persist the outcome of a delivery run. Returns True if it was recorded.

    Guarded on `callback_delivered_at IS NULL`, which makes a successful
    delivery terminal: a later run that somehow raced through can neither
    overwrite the delivery timestamp nor append its attempts.
    """
    result = await conn.execute(
        f"""
        UPDATE {_TABLE}
        SET callback_attempts = callback_attempts + $2,
            callback_delivered_at = CASE WHEN $3 THEN now() ELSE NULL END,
            callback_last_error = $4
        WHERE id = $1 AND callback_delivered_at IS NULL
        """,
        handoff_id,
        attempts,
        delivered,
        error,
    )
    return isinstance(result, str) and not result.endswith(" 0")
