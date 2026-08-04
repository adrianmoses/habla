"""Read-only learner-state queries shared by the production `/api/learner*`
endpoints (spec #019) and the dev `/dev/learner` inspector.

Both surfaces read the same relational learner state; keeping the SQL here
means they cannot drift. All payloads are JSON-ready: timestamps are ISO-8601
strings and JSONB is decoded to objects. Nothing here writes.

Nothing here reads the AGE graph either, and that is now a settled position
rather than a pending one: #022 established that **adaptivity is relational**
and the graph is an inspection artifact. The one graph reader in the codebase
is ``hable_ya.learner.graph.graph_summary``, surfaced only on the dev-gated
``/dev/learner``. If a future spec makes the graph load-bearing, this docstring
is the first thing that should stop being true.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from hable_ya.learner.profile import LearnerProfileRepo, is_calibrated_async

TOP_ERRORS = 10
TOP_VOCAB = 10
RECENT_DOMAINS = 5


def _signals_to_dict(raw: Any) -> dict[str, Any]:
    """asyncpg returns JSONB as str without a registered codec; decode."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


async def profile_payload(pool: asyncpg.Pool) -> dict[str, Any]:
    """The `/api/learner` body: profile snapshot + top errors/vocab + themes."""
    snapshot = await LearnerProfileRepo(pool).get()
    async with pool.acquire() as conn:
        is_calibrated = await is_calibrated_async(conn)
        # `display_name` rides along here rather than on the snapshot: the
        # snapshot feeds the tutor's system prompt, and the name must have no
        # path to it (spec #021 Key Decision 2).
        profile_extras = await conn.fetchrow(
            """
            SELECT stable_sessions_at_band, last_band_change_at, display_name
            FROM learner_profile WHERE id = 1
            """
        )
        error_rows = await conn.fetch(
            """
            SELECT category, count, last_seen_at
            FROM error_counts
            ORDER BY count DESC, last_seen_at DESC
            LIMIT $1
            """,
            TOP_ERRORS,
        )
        vocab_rows = await conn.fetch(
            """
            SELECT lemma, production_count, last_seen_at
            FROM vocabulary_items
            ORDER BY last_seen_at DESC
            LIMIT $1
            """,
            TOP_VOCAB,
        )
        domain_rows = await conn.fetch(
            """
            SELECT theme_domain, started_at
            FROM sessions
            WHERE theme_domain IS NOT NULL
            ORDER BY started_at DESC
            LIMIT $1
            """,
            RECENT_DOMAINS,
        )
    stable = (
        int(profile_extras["stable_sessions_at_band"])
        if profile_extras is not None
        else 0
    )
    last_change = (
        profile_extras["last_band_change_at"] if profile_extras is not None else None
    )
    display_name = (
        profile_extras["display_name"] if profile_extras is not None else None
    )
    return {
        "band": snapshot.band,
        "display_name": display_name,
        "sessions_completed": snapshot.sessions_completed,
        "l1_reliance": snapshot.l1_reliance,
        "speech_fluency": snapshot.speech_fluency,
        "error_patterns": snapshot.error_patterns,
        "vocab_strengths": snapshot.vocab_strengths,
        "is_calibrated": is_calibrated,
        "stable_sessions_at_band": stable,
        "last_band_change_at": (
            last_change.isoformat() if last_change is not None else None
        ),
        "top_errors": [
            {
                "category": r["category"],
                "count": r["count"],
                "last_seen_at": r["last_seen_at"].isoformat(),
            }
            for r in error_rows
        ],
        "top_vocab": [
            {
                "lemma": r["lemma"],
                "production_count": r["production_count"],
                "last_seen_at": r["last_seen_at"].isoformat(),
            }
            for r in vocab_rows
        ],
        "recent_theme_domains": [r["theme_domain"] for r in domain_rows],
    }


async def session_history(
    pool: asyncpg.Pool, *, limit: int, offset: int
) -> list[dict[str, Any]]:
    """Paginated session list, newest first, with a per-session turn count.

    LEFT JOIN so a session that logged no turns still appears with
    ``turn_count = 0`` rather than dropping out of the history.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                s.session_id,
                s.started_at,
                s.ended_at,
                s.theme_domain,
                s.band_at_start,
                s.mode,
                COALESCE(t.turn_count, 0) AS turn_count
            FROM sessions s
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS turn_count
                FROM turns
                GROUP BY session_id
            ) t ON t.session_id = s.session_id
            ORDER BY s.started_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
    return [
        {
            "session_id": r["session_id"],
            "started_at": r["started_at"].isoformat(),
            "ended_at": (
                r["ended_at"].isoformat() if r["ended_at"] is not None else None
            ),
            "theme_domain": r["theme_domain"],
            "band_at_start": r["band_at_start"],
            "mode": r["mode"],
            "turn_count": int(r["turn_count"]),
        }
        for r in rows
    ]


async def band_history(pool: asyncpg.Pool, *, limit: int) -> list[dict[str, Any]]:
    """Band-change audit rows, newest first; `signals` decoded to an object."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, from_band, to_band, reason, signals, changed_at
            FROM band_history
            ORDER BY changed_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [
        {
            "id": r["id"],
            "from_band": r["from_band"],
            "to_band": r["to_band"],
            "reason": r["reason"],
            "signals": _signals_to_dict(r["signals"]),
            "changed_at": r["changed_at"].isoformat(),
        }
        for r in rows
    ]
