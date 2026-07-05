"""LearnerProfileRepo — snapshot + mutations for the single-tenant profile row.

The snapshot is the handoff object the prompt builder consumes. It combines
the static `learner_profile` row with two rolling-window aggregates derived
from the last K=20 turns (`L1_reliance`, `speech_fluency`) and the top-N
reads from `error_counts` / `vocabulary_items`. Aggregation rules live in
:mod:`hable_ya.learner.aggregations` so the agent-eval accumulator can share
them; this module owns persistence and adapts SQL rows into the pure
function's input shape.
"""

from __future__ import annotations

import logging
from collections import Counter

import asyncpg

from eval.fixtures.schema import CEFRBand, FluencySignal, LearnerProfile
from hable_ya.learner.aggregations import (
    LearnerProfileSnapshot,
    compute_snapshot,
)
from hable_ya.learner.bands import BAND_MIDPOINT, is_valid_cefr_band

__all__ = [
    "LearnerProfileRepo",
    "LearnerProfileSnapshot",
    "current_band",
    "is_calibrated_async",
    "snapshot_to_profile",
]

logger = logging.getLogger(__name__)

# Backwards-compatible alias for tests that imported the underscore name.
_BAND_MIDPOINT = BAND_MIDPOINT


def snapshot_to_profile(
    snapshot: LearnerProfileSnapshot,
    *,
    is_calibrated: bool = False,
) -> LearnerProfile:
    """Map a `LearnerProfileSnapshot` into the prompt-renderer's profile shape.

    The runtime prompt builder and the agent-eval orchestrator both call
    this so the rendered system prompt is identical whether the snapshot
    came from the DB or an in-memory accumulator.

    Spec 049: ``is_calibrated`` is now derived from the existence of a
    ``band_history`` row with ``reason='placement'`` (see
    :func:`is_calibrated_async`), not from ``sessions_completed > 0``. A
    completed session that produced no log_turn calls — pathological but
    possible — must not flip ``is_calibrated``. The eval-accumulator path
    has no DB and passes ``False``.
    """
    level = _BAND_MIDPOINT.get(snapshot.band, 0.5)
    return LearnerProfile(
        production_level=level,
        L1_reliance=snapshot.l1_reliance,
        speech_fluency=snapshot.speech_fluency,
        is_calibrated=is_calibrated,
        sessions_completed=snapshot.sessions_completed,
        vocab_strengths=list(snapshot.vocab_strengths),
        error_patterns=list(snapshot.error_patterns),
    )


_IS_CALIBRATED_SQL = (
    "SELECT EXISTS(SELECT 1 FROM band_history WHERE reason='placement')"
)
_CURRENT_BAND_SQL = "SELECT band FROM learner_profile WHERE id = 1"


async def is_calibrated_async(
    pool_or_conn: asyncpg.Pool | asyncpg.Connection,
) -> bool:
    """True iff a ``band_history`` row with ``reason='placement'`` exists.

    Accepts a pool (acquires a connection) or an already-acquired
    connection so callers in a transaction can avoid a redundant acquire.
    """
    if isinstance(pool_or_conn, asyncpg.Pool):
        async with pool_or_conn.acquire() as conn:
            result = await conn.fetchval(_IS_CALIBRATED_SQL)
    else:
        result = await pool_or_conn.fetchval(_IS_CALIBRATED_SQL)
    return bool(result)


async def current_band(
    pool_or_conn: asyncpg.Pool | asyncpg.Connection,
) -> CEFRBand:
    """Read the live band from ``learner_profile``.

    Returns ``"A2"`` if the profile row is missing or carries an
    unexpected value — same neutral posture as :meth:`LearnerProfileRepo.get`.
    """
    if isinstance(pool_or_conn, asyncpg.Pool):
        async with pool_or_conn.acquire() as conn:
            band = await conn.fetchval(_CURRENT_BAND_SQL)
    else:
        band = await pool_or_conn.fetchval(_CURRENT_BAND_SQL)
    return band if is_valid_cefr_band(band) else "A2"


class LearnerProfileRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(
        self,
        *,
        window_turns: int = 20,
        top_errors: int = 3,
        top_vocab: int = 5,
    ) -> LearnerProfileSnapshot:
        async with self._pool.acquire() as conn:
            profile_row = await conn.fetchrow(
                "SELECT band, sessions_completed FROM learner_profile WHERE id = 1"
            )
            if profile_row is None:
                logger.warning(
                    "learner_profile row missing — returning neutral snapshot"
                )
                return LearnerProfileSnapshot(band="A2", sessions_completed=0)

            band: CEFRBand = profile_row["band"]
            sessions_completed = int(profile_row["sessions_completed"])

            turn_rows = await conn.fetch(
                """
                SELECT L1_used, fluency_signal
                FROM turns
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                window_turns,
            )
            error_rows = await conn.fetch(
                "SELECT category, count, last_seen_at FROM error_counts"
            )
            vocab_rows = await conn.fetch(
                """
                SELECT lemma, last_seen_at FROM vocabulary_items
                ORDER BY last_seen_at DESC
                LIMIT $1
                """,
                top_vocab,
            )

        l1_used_flags = [bool(r["l1_used"]) for r in turn_rows]
        fluency_signals: list[FluencySignal] = [
            r["fluency_signal"] for r in turn_rows
        ]
        error_counter: Counter[str] = Counter(
            {r["category"]: int(r["count"]) for r in error_rows}
        )
        error_last_seen = {r["category"]: r["last_seen_at"] for r in error_rows}
        vocab_last_seen = {r["lemma"]: r["last_seen_at"] for r in vocab_rows}

        return compute_snapshot(
            band=band,
            sessions_completed=sessions_completed,
            l1_used_flags=l1_used_flags,
            fluency_signals=fluency_signals,
            error_counter=error_counter,
            error_last_seen=error_last_seen,
            vocab_last_seen=vocab_last_seen,
            top_errors=top_errors,
            top_vocab=top_vocab,
        )

    async def increment_session_count(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE learner_profile
                SET sessions_completed = sessions_completed + 1,
                    updated_at = now()
                WHERE id = 1
                """
            )

    async def set_band(self, band: CEFRBand) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE learner_profile SET band = $1, updated_at = now() WHERE id = 1",
                band,
            )
