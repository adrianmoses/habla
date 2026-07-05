"""Development-only observation + learner-profile inspection endpoints.

Mounted only when ``settings.dev_endpoints_enabled`` is true.

* ``GET /dev/observations`` — recent :class:`TurnObservation` entries held in
  the sink's ring buffer, plus the running ``missing`` + ``ingest_failed``
  counters so the project owner can watch the fine-tuned Gemma's ~80%
  log_turn emission rate and the learner-DB write health in real time.
* ``GET /dev/learner`` (#029) — current profile snapshot, top errors + vocab,
  recent theme domains; correlates with ``/dev/observations`` so a reviewer
  can see the profile update produced by each turn.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from hable_ya.learner.profile import LearnerProfileRepo, is_calibrated_async

router = APIRouter()

DEV_LEARNER_RECENT_TURNS = 10
DEV_LEARNER_BAND_HISTORY = 5


@router.get("/dev/observations")
async def get_observations(
    request: Request, n: int = Query(100, ge=1, le=1000)
) -> dict[str, Any]:
    sink = request.app.state.observation_sink
    return {
        "missing": sink.missing,
        "ingest_failed": getattr(sink, "ingest_failed", 0),
        "band_missing": getattr(sink, "band_missing", 0),
        "leveling_failed": getattr(sink, "leveling_failed", 0),
        "observations": [asdict(obs) for obs in sink.recent(n)],
    }


@router.get("/dev/learner")
async def get_learner(request: Request) -> dict[str, Any]:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db pool not ready")
    snapshot = await LearnerProfileRepo(pool).get()
    async with pool.acquire() as conn:
        is_calibrated = await is_calibrated_async(conn)
        profile_extras = await conn.fetchrow(
            """
            SELECT stable_sessions_at_band, last_band_change_at
            FROM learner_profile WHERE id = 1
            """
        )
        error_rows = await conn.fetch(
            """
            SELECT category, count, last_seen_at
            FROM error_counts
            ORDER BY count DESC, last_seen_at DESC
            LIMIT 10
            """
        )
        vocab_rows = await conn.fetch(
            """
            SELECT lemma, production_count, last_seen_at
            FROM vocabulary_items
            ORDER BY last_seen_at DESC
            LIMIT 10
            """
        )
        domain_rows = await conn.fetch(
            """
            SELECT theme_domain, started_at
            FROM sessions
            WHERE theme_domain IS NOT NULL
            ORDER BY started_at DESC
            LIMIT 5
            """
        )
        band_history_rows = await conn.fetch(
            """
            SELECT id, from_band, to_band, reason, signals, changed_at
            FROM band_history
            ORDER BY changed_at DESC
            LIMIT $1
            """,
            DEV_LEARNER_BAND_HISTORY,
        )
        recent_turn_rows = await conn.fetch(
            """
            SELECT cefr_band, timestamp
            FROM turns
            ORDER BY timestamp DESC
            LIMIT $1
            """,
            DEV_LEARNER_RECENT_TURNS,
        )
    stable = (
        int(profile_extras["stable_sessions_at_band"])
        if profile_extras is not None
        else 0
    )
    last_change = (
        profile_extras["last_band_change_at"]
        if profile_extras is not None
        else None
    )
    return {
        "profile": {
            "band": snapshot.band,
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
        },
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
        "band_history": [
            {
                "id": r["id"],
                "from_band": r["from_band"],
                "to_band": r["to_band"],
                "reason": r["reason"],
                "signals": _signals_to_dict(r["signals"]),
                "changed_at": r["changed_at"].isoformat(),
            }
            for r in band_history_rows
        ],
        "recent_turn_bands": [
            {
                "cefr_band": r["cefr_band"],
                "timestamp": r["timestamp"].isoformat(),
            }
            for r in recent_turn_rows
        ],
    }


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
