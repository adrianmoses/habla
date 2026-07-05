"""Async wrapper that turns the pure leveling decisions into DB writes.

Two end-of-session entry points:

* :meth:`LevelingService.run_placement` — runs once at the end of an
  uncalibrated learner's session. Reads the session's ``cefr_band``
  values, calls :func:`place_band`, and on a Some result writes the new
  band + ``band_history`` row in one transaction. Abstains silently if
  ``place_band`` returns ``None`` (caller stays uncalibrated and re-enters
  the diagnostic on the next session).
* :meth:`LevelingService.run_leveling` — runs at the end of every
  post-placement session. Reads the last ``leveling_window_sessions``
  sessions' non-null ``turns.cefr_band`` values, runs
  :func:`evaluate_leveling`, and writes either a band flip + audit row,
  or just bumps / resets ``stable_sessions_at_band``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

import asyncpg

from eval.fixtures.schema import CEFRBand
from hable_ya.config import settings
from hable_ya.learner.bands import is_valid_cefr_band
from hable_ya.learner.leveling.policy import (
    LevelingDecision,
    PlacementDecision,
    evaluate_leveling,
    place_band,
)

logger = logging.getLogger("hable_ya.learner.leveling")

LearnerId = 1  # single-tenant: one learner per deployment.

LevelingReason = Literal["placement", "auto_promote", "auto_demote", "manual"]


class LevelingService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def run_placement(
        self,
        *,
        session_id: str,
    ) -> PlacementDecision | None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT cefr_band
                FROM turns
                WHERE session_id = $1
                ORDER BY timestamp ASC
                """,
                session_id,
            )
            turn_bands: list[CEFRBand | None] = [
                r["cefr_band"] if is_valid_cefr_band(r["cefr_band"]) else None
                for r in rows
            ]
            decision = place_band(
                turn_bands,
                floor_band=settings.default_learner_band,  # type: ignore[arg-type]
                min_valid_turns=settings.placement_min_valid_turns,
            )
            if decision is None:
                logger.info(
                    "session %s: placement abstained — %d/%d turns had a "
                    "valid cefr_band (need %d)",
                    session_id,
                    sum(1 for b in turn_bands if b is not None),
                    len(turn_bands),
                    settings.placement_min_valid_turns,
                )
                return None
            await self._apply_band_change(
                conn,
                from_band=None,
                to_band=decision.band,
                reason="placement",
                signals={**decision.signals, "session_id": session_id},
            )
        logger.info(
            "session %s: placement → %s (signals=%s)",
            session_id,
            decision.band,
            decision.signals,
        )
        return decision

    async def run_leveling(
        self,
        *,
        current_band: CEFRBand,
    ) -> LevelingDecision:
        async with self._pool.acquire() as conn:
            stable_sessions, recent_bands = await self._fetch_leveling_inputs(
                conn
            )
            decision = evaluate_leveling(
                current_band=current_band,
                recent_turn_bands=recent_bands,
                stable_sessions=stable_sessions,
                promote_consecutive=settings.leveling_promote_consecutive,
                demote_consecutive=settings.leveling_demote_consecutive,
            )
            if decision.reason != "stable":
                await self._apply_band_change(
                    conn,
                    from_band=current_band,
                    to_band=decision.new_band,
                    reason=decision.reason,
                    signals=decision.signals,
                )
                logger.info(
                    "leveling: %s → %s (%s)",
                    current_band,
                    decision.new_band,
                    decision.reason,
                )
                return decision

            toward = decision.signals.get("toward")
            # Toward current band or a borderline demote signal: reset the
            # streak so the mixed sequence "2 promote + 1 stable + 1 promote"
            # cannot promote on the 4th session. Otherwise accumulate.
            new_count_expr = (
                "0"
                if toward in (current_band, "borderline")
                else "stable_sessions_at_band + 1"
            )
            await conn.execute(
                f"""
                UPDATE learner_profile
                SET stable_sessions_at_band = {new_count_expr},
                    updated_at = now()
                WHERE id = $1
                """,
                LearnerId,
            )
            return decision

    @staticmethod
    async def _fetch_leveling_inputs(
        conn: asyncpg.Connection,
    ) -> tuple[int, list[CEFRBand]]:
        """Single round-trip pair: hysteresis counter + the rolling window.

        ``stable_sessions_at_band`` is one fetchval; the rolling window
        is one JOIN that limits to the last N sessions and pulls their
        non-null cefr_band turns in chronological order.
        """
        stable_sessions = int(
            await conn.fetchval(
                "SELECT stable_sessions_at_band FROM learner_profile "
                "WHERE id = $1",
                LearnerId,
            )
            or 0
        )
        rows = await conn.fetch(
            """
            WITH recent_sessions AS (
                SELECT session_id
                FROM sessions
                ORDER BY started_at DESC
                LIMIT $1
            )
            SELECT t.cefr_band
            FROM turns t
            JOIN recent_sessions rs USING (session_id)
            WHERE t.cefr_band IS NOT NULL
            ORDER BY t.timestamp ASC
            """,
            settings.leveling_window_sessions,
        )
        bands: list[CEFRBand] = [
            r["cefr_band"] for r in rows if is_valid_cefr_band(r["cefr_band"])
        ]
        return stable_sessions, bands

    @staticmethod
    async def _apply_band_change(
        conn: asyncpg.Connection,
        *,
        from_band: CEFRBand | None,
        to_band: CEFRBand,
        reason: LevelingReason,
        signals: dict[str, Any],
    ) -> None:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO band_history
                    (from_band, to_band, reason, signals, changed_at)
                VALUES ($1, $2, $3, $4::jsonb, now())
                """,
                from_band,
                to_band,
                reason,
                json.dumps(signals, default=str),
            )
            await conn.execute(
                """
                UPDATE learner_profile
                SET band                    = $1,
                    stable_sessions_at_band = 0,
                    last_band_change_at     = now(),
                    updated_at              = now()
                WHERE id = $2
                """,
                to_band,
                LearnerId,
            )
