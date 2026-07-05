"""TurnIngestService — one transaction per ``log_turn`` observation.

Composes the learner-state writes (turn row, error observations, error
counts, vocabulary items, AGE graph upserts) inside a single
``conn.transaction()`` so the relational aggregates never drift from the
graph. Called from the tool handler on the happy path of every validated
``log_turn`` call; failures are logged + counted (on the sink's
``ingest_failed``) rather than propagated, so a DB outage never takes
down the live session.

Spec 049: ``end_session`` also runs the placement / leveling decision
through :class:`LevelingService`. Failures there are logged but never
re-raised — the session-end path stays best-effort.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import asyncpg

from eval.fixtures.schema import CEFRBand
from hable_ya.learner import graph
from hable_ya.learner.errors import ErrorRepo
from hable_ya.learner.leveling import LevelingService
from hable_ya.learner.profile import (
    LearnerProfileRepo,
    current_band,
    is_calibrated_async,
)
from hable_ya.learner.vocabulary import VocabularyRepo
from hable_ya.runtime.observations import TurnObservation, TurnObservationSink

logger = logging.getLogger("hable_ya.learner.ingest")


def _parse_timestamp(ts_iso: str) -> datetime:
    # TurnObservation.now emits millisecond-precision ISO with UTC offset.
    # datetime.fromisoformat handles that since Python 3.11.
    return datetime.fromisoformat(ts_iso)


class TurnIngestService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        leveling: LevelingService | None = None,
        sink: TurnObservationSink | None = None,
    ) -> None:
        self._pool = pool
        self._profile = LearnerProfileRepo(pool)
        self._leveling = leveling
        # Optional so end_session can bump ``leveling_failed`` on a write
        # failure; the integration tests use the ingest service without
        # the sink and that's fine.
        self._sink = sink

    async def ingest(self, obs: TurnObservation) -> None:
        at = _parse_timestamp(obs.timestamp_iso)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                turn_id = await self._insert_turn(conn, obs, at)
                if obs.errors:
                    categories = await ErrorRepo.record(
                        conn, turn_id=turn_id, errors=obs.errors, at=at
                    )
                else:
                    categories = []
                lemmas = await VocabularyRepo.record(
                    conn, utterance=obs.learner_utterance, at=at
                )
                for category in set(categories):
                    await graph.upsert_error_pattern(conn, category=category, at=at)
                for lemma in lemmas:
                    await graph.upsert_vocab(conn, lemma=lemma, at=at)

    async def start_session(
        self,
        *,
        session_id: str,
        theme_domain: str,
        band: CEFRBand,
        at: datetime | None = None,
    ) -> None:
        when = at or datetime.now(UTC)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO sessions
                        (session_id, started_at, theme_domain, band_at_start)
                    VALUES ($1, COALESCE($2, now()), $3, $4)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    session_id,
                    at,
                    theme_domain,
                    band,
                )
                await graph.ensure_learner_node(conn)
                await graph.link_session_to_scenario(
                    conn, scenario_domain=theme_domain, band=band, at=when
                )
        await self._profile.increment_session_count()

    async def end_session(self, *, session_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET ended_at = now() WHERE session_id = $1",
                session_id,
            )
            if self._leveling is None:
                return
            calibrated = await is_calibrated_async(conn)
            band = await current_band(conn) if calibrated else None
        # Leveling acquires its own connection (it manages its own
        # transaction + reads); doing it inside the acquire above would
        # double-up. A DB hiccup must not crash the WebSocket handler.
        try:
            if not calibrated:
                await self._leveling.run_placement(session_id=session_id)
            else:
                assert band is not None
                await self._leveling.run_leveling(current_band=band)
        except Exception:
            logger.exception("session %s: leveling failed", session_id)
            if self._sink is not None:
                self._sink.leveling_failed += 1

    @staticmethod
    async def _insert_turn(
        conn: asyncpg.Connection,
        obs: TurnObservation,
        at: datetime,
    ) -> int:
        # The sessions row must exist before a turn can FK to it. In normal
        # operation `start_session` creates it at connect time; for integration
        # tests that bypass start_session, stitch a row lazily so the happy
        # path doesn't crash on a missing parent.
        await conn.execute(
            """
            INSERT INTO sessions (session_id, band_at_start)
            VALUES ($1, 'A2')
            ON CONFLICT (session_id) DO NOTHING
            """,
            obs.session_id,
        )
        return int(
            await conn.fetchval(
                """
                INSERT INTO turns
                    (session_id, timestamp, learner_utterance,
                     fluency_signal, L1_used, cefr_band)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                obs.session_id,
                at,
                obs.learner_utterance,
                obs.fluency_signal,
                obs.L1_used,
                obs.cefr_band,
            )
        )
