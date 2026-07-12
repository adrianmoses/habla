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

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from hable_ya.learner import read

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
    """Dev inspector: the production `/api/learner` payload (shared read module,
    spec #019) reshaped under a ``profile`` key, plus the dev-only
    ``recent_turn_bands`` per-turn trace and `band_history`."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db pool not ready")
    payload = await read.profile_payload(pool)
    band_history = await read.band_history(pool, limit=DEV_LEARNER_BAND_HISTORY)
    async with pool.acquire() as conn:
        recent_turn_rows = await conn.fetch(
            """
            SELECT cefr_band, timestamp
            FROM turns
            ORDER BY timestamp DESC
            LIMIT $1
            """,
            DEV_LEARNER_RECENT_TURNS,
        )
    top_errors = payload.pop("top_errors")
    top_vocab = payload.pop("top_vocab")
    recent_theme_domains = payload.pop("recent_theme_domains")
    return {
        "profile": payload,
        "top_errors": top_errors,
        "top_vocab": top_vocab,
        "recent_theme_domains": recent_theme_domains,
        "band_history": band_history,
        "recent_turn_bands": [
            {
                "cefr_band": r["cefr_band"],
                "timestamp": r["timestamp"].isoformat(),
            }
            for r in recent_turn_rows
        ],
    }
