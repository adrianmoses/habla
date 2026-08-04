"""TurnIngestService — one transaction per ``log_turn`` observation.

Composes the relational learner-state writes (turn row, error observations,
error counts, vocabulary items) inside a single ``conn.transaction()``. Called
from the tool handler on the happy path of every validated ``log_turn`` call;
failures are logged + counted (on the sink's ``ingest_failed``) rather than
propagated, so a DB outage never takes down the live session.

Spec 022: the AGE graph upserts run *after* that transaction commits, and are
best-effort — the graph is an inspection artifact that no adaptation reads, so
a cypher failure must not discard relational state that is genuinely
load-bearing. Failures bump the sink's ``graph_failed``. The consequence is
that graph and relational state can now drift under failure; that is the
intended trade, and ``graph_failed`` is how it stays visible.

Spec 049: ``end_session`` also runs the placement / leveling decision
through :class:`LevelingService`. Failures there are logged but never
re-raised — the session-end path stays best-effort.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import asyncpg

from eval.fixtures.schema import CEFRBand, ConversationMode
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
            # Graph upserts run *after* the relational commit, best-effort
            # (spec #022, OQ2). They were inside the transaction until the
            # graph's role was settled: it is an inspection artifact, read by
            # nothing that adapts, so letting a cypher failure discard a turn's
            # real learner state traded something load-bearing for something
            # decorative. Measured at ~3ms and ~59% of the transaction, the
            # move costs no latency — it is about what a failure may destroy.
            await self._upsert_graph(conn, categories=categories, lemmas=lemmas, at=at)

    async def _upsert_graph(
        self,
        conn: asyncpg.Connection,
        *,
        categories: list[str],
        lemmas: list[str],
        at: datetime,
    ) -> None:
        """Best-effort AGE upserts; logged and counted, never raised."""
        try:
            for category in set(categories):
                await graph.upsert_error_pattern(conn, category=category, at=at)
            for lemma in lemmas:
                await graph.upsert_vocab(conn, lemma=lemma, at=at)
        except Exception:
            logger.warning(
                "graph upsert failed; relational state committed", exc_info=True
            )
            if self._sink is not None:
                self._sink.graph_failed += 1

    async def start_session(
        self,
        *,
        session_id: str,
        theme_domain: str,
        band: CEFRBand,
        mode: ConversationMode = "open",
        at: datetime | None = None,
    ) -> None:
        when = at or datetime.now(UTC)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO sessions
                        (session_id, started_at, theme_domain, band_at_start, mode)
                    VALUES ($1, COALESCE($2, now()), $3, $4, $5)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    session_id,
                    at,
                    theme_domain,
                    band,
                    mode,
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
                     fluency_signal, L1_used, cefr_band, raw_extra)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                RETURNING id
                """,
                obs.session_id,
                at,
                obs.learner_utterance,
                obs.fluency_signal,
                obs.L1_used,
                obs.cefr_band,
                # Spec #024: extra (e.g. response_latency_ms) was previously
                # dropped on the DB path; asyncpg takes JSONB as text.
                json.dumps(obs.extra, ensure_ascii=False),
            )
        )
