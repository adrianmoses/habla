"""Seed the learner tables with realistic development data (spec #020).

The runtime writes learner state one turn at a time, so a fresh database shows
every frontend surface in its empty state. This script fabricates the *shape* of
a learner who has been practising for three weeks — sessions across two bands, a
placement plus a promotion, error and vocabulary aggregates — so the `web/`
progress screens can be built and eyeballed against something other than zeros.

Dev-only. It writes directly to the tables rather than going through
`TurnIngestService`, because the point is to produce a plausible *end state*
cheaply, not to exercise the ingest path (`tests/` already does that). It never
runs in production: there is no caller outside a developer's shell.

    docker compose up -d db
    HABLE_YA_DATABASE_URL=postgresql://hable_ya:hable_ya@localhost:5433/hable_ya \
        uv run python scripts/seed_dev_learner.py --reset

`--reset` truncates the learner tables first (same statement the
`clean_learner_state` test fixture uses) so reseeding is repeatable.

Deliberate properties the frontend needs to exercise:

- A **3-day streak** ending today (today / yesterday / two days ago), then a gap
  — so a streak calculation that ignores gaps is visibly wrong.
- One session with **`ended_at IS NULL`** (the in-progress / crashed case).
- Sessions with **`mode IS NULL`** (pre-#023 rows) alongside all four modes.
- Error categories that are **not** in `eval.agent.personas.ALLOWED_ERROR_PATTERNS`
  — `errors[].type` is a free-form string in the `log_turn` schema with no enum
  (`hable_ya/tools/schema.py`), so the UI must survive whatever Claude writes.
- More than 20 turns, since `l1_reliance` / `speech_fluency` are computed over a
  trailing 20-turn window (`hable_ya/learner/profile.py`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import asyncpg

from hable_ya.db import close_pool, open_pool

logger = logging.getLogger("seed_dev_learner")

TRUNCATE_SQL = (
    "TRUNCATE error_observations, error_counts, vocabulary_items, "
    "turns, sessions, band_history RESTART IDENTITY CASCADE"
)

# (days_ago, theme_domain, band_at_start, mode, n_turns, ended)
# Days 0/1/2 are consecutive → a 3-day streak; day 3 is absent → it breaks.
_SESSIONS: tuple[tuple[int, str, str, str | None, int, bool], ...] = (
    (20, "presentarse", "A2", None, 4, True),
    (18, "pedir un café", "A2", None, 3, True),
    (15, "hablar de la familia", "A2", "open", 3, True),
    (13, "comprar en el mercado", "A2", "role_play", 4, True),
    (11, "planes para el fin de semana", "A2", "open", 3, True),
    (9, "pedir direcciones", "A2", "interview", 2, True),
    (7, "hablar del clima", "A2", "open", 3, True),
    (5, "mi día normal", "A2", "open", 4, True),
    (4, "debate: el transporte público", "B1", "debate", 5, True),
    (2, "comida favorita", "B1", "open", 3, True),
    (1, "planear un viaje a Oaxaca", "B1", "role_play", 4, True),
    (0, "contar un sueño raro", "B1", "debate", 2, False),
)

# Utterances cycle per session; band/fluency track the session's band so the
# trailing-20-turn aggregates read as a learner who is improving.
_A2_UTTERANCES: tuple[tuple[str, str, bool], ...] = (
    ("Hola, me llamo Ana y soy de Boston.", "moderate", False),
    ("Yo trabajo en una oficina, es muy... busy.", "weak", True),
    ("Me gusta el café con leche por la mañana.", "moderate", False),
    ("Mi familia es grande, tengo dos hermanas.", "moderate", False),
    ("El fin de semana voy al parque con mis amigos.", "moderate", False),
)
_B1_UTTERANCES: tuple[tuple[str, str, bool], ...] = (
    ("Creo que el transporte público debería ser gratuito.", "strong", False),
    ("Aunque es caro, pienso que vale la pena.", "strong", False),
    ("Cuando era niña, viajaba mucho con mi familia.", "moderate", False),
    ("Ayer fui al mercado y compré unas frutas muy ricas.", "strong", False),
    ("No estoy de acuerdo, porque la gente necesita el coche.", "strong", False),
)

# Mixed on purpose: the first five are the curated eval vocabulary
# (`ALLOWED_ERROR_PATTERNS`); the last two are the kind of off-vocabulary label
# Claude actually emits, and must degrade gracefully in the UI.
_ERROR_COUNTS: tuple[tuple[str, int, int], ...] = (
    ("gender_agreement", 14, 1),
    ("ser_estar", 9, 2),
    ("preterite_imperfect", 7, 4),
    ("por_para", 5, 5),
    ("subjunctive_avoidance", 3, 7),
    ("concordancia de número", 2, 9),
    ("verb tense confusion", 1, 13),
)

_VOCAB: tuple[tuple[str, str, int, int], ...] = (
    ("viajar", "viajaba", 9, 1),
    ("gustar", "gusta", 8, 1),
    ("comprar", "compré", 7, 1),
    ("pensar", "pienso", 6, 2),
    ("trabajar", "trabajo", 6, 4),
    ("familia", "familia", 5, 5),
    ("mercado", "mercado", 4, 4),
    ("transporte", "transporte", 4, 4),
    ("café", "café", 4, 7),
    ("amigo", "amigos", 3, 9),
    ("parque", "parque", 3, 11),
    ("fruta", "frutas", 2, 1),
    ("sueño", "sueño", 2, 0),
    ("coche", "coche", 2, 4),
    ("hermana", "hermanas", 2, 15),
)


def _at(now: datetime, days_ago: int, *, hour: int = 19) -> datetime:
    """A timestamp `days_ago` days back, pinned to a plausible evening hour."""
    day = now - timedelta(days=days_ago)
    return day.replace(hour=hour, minute=12, second=0, microsecond=0)


async def _seed_sessions(conn: asyncpg.Connection, now: datetime) -> None:
    for days_ago, theme, band, mode, n_turns, ended in _SESSIONS:
        started = _at(now, days_ago)
        # Realistic session lengths: ~2.5 min per turn.
        ended_at = started + timedelta(minutes=3 * n_turns) if ended else None
        session_id = f"seed-{days_ago:02d}-{theme[:12].replace(' ', '-')}"
        await conn.execute(
            """
            INSERT INTO sessions
                (session_id, started_at, ended_at, theme_domain, band_at_start, mode)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (session_id) DO NOTHING
            """,
            session_id,
            started,
            ended_at,
            theme,
            band,
            mode,
        )
        pool_ = _B1_UTTERANCES if band == "B1" else _A2_UTTERANCES
        for i in range(n_turns):
            utterance, fluency, l1_used = pool_[i % len(pool_)]
            turn_id = await conn.fetchval(
                """
                INSERT INTO turns
                    (session_id, timestamp, learner_utterance, fluency_signal,
                     l1_used, cefr_band, raw_extra)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                session_id,
                started + timedelta(minutes=3 * i),
                utterance,
                fluency,
                l1_used,
                band,
                # #024 writes response_latency_ms here. No endpoint exposes it
                # yet (out of scope for #020), but seeding it keeps the column
                # honest and gives a future aggregate something to read.
                json.dumps({"response_latency_ms": 900 + (i * 137) % 1600}),
            )
            if i == 0 and days_ago % 2 == 0:
                await conn.execute(
                    """
                    INSERT INTO error_observations
                        (turn_id, category, produced_form, target_form)
                    VALUES ($1, $2, $3, $4)
                    """,
                    turn_id,
                    _ERROR_COUNTS[days_ago % len(_ERROR_COUNTS)][0],
                    "la problema",
                    "el problema",
                )


async def _seed_aggregates(conn: asyncpg.Connection, now: datetime) -> None:
    for category, count, days_ago in _ERROR_COUNTS:
        await conn.execute(
            """
            INSERT INTO error_counts (category, count, last_seen_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (category) DO UPDATE
              SET count = EXCLUDED.count, last_seen_at = EXCLUDED.last_seen_at
            """,
            category,
            count,
            _at(now, days_ago),
        )
    for lemma, sample, count, days_ago in _VOCAB:
        await conn.execute(
            """
            INSERT INTO vocabulary_items
                (lemma, sample_form, production_count, first_seen_at, last_seen_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (lemma) DO UPDATE
              SET production_count = EXCLUDED.production_count,
                  last_seen_at = EXCLUDED.last_seen_at
            """,
            lemma,
            sample,
            count,
            _at(now, 20),
            _at(now, days_ago),
        )


async def _seed_bands(conn: asyncpg.Connection, now: datetime) -> None:
    """A placement (which is what flips `is_calibrated`) plus one promotion."""
    await conn.execute(
        """
        INSERT INTO band_history (from_band, to_band, reason, signals, changed_at)
        VALUES (NULL, 'A2', 'placement', $1, $2)
        """,
        json.dumps({"turns_observed": 4, "diagnostic": True}),
        _at(now, 20, hour=19),
    )
    await conn.execute(
        """
        INSERT INTO band_history (from_band, to_band, reason, signals, changed_at)
        VALUES ('A2', 'B1', 'auto_promote', $1, $2)
        """,
        json.dumps(
            {
                "sessions_at_band": 8,
                "band_mode": "B1",
                "l1_reliance": 0.11,
                "speech_fluency": 0.78,
            }
        ),
        _at(now, 5, hour=20),
    )
    await conn.execute(
        """
        UPDATE learner_profile
           SET band = 'B1',
               sessions_completed = $1,
               stable_sessions_at_band = 4,
               last_band_change_at = $2
         WHERE id = 1
        """,
        len(_SESSIONS),
        _at(now, 5, hour=20),
    )


async def amain(reset: bool) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    now = datetime.now(UTC)
    pool = await open_pool()
    try:
        async with pool.acquire() as conn:
            if reset:
                logger.info("Truncating learner tables")
                await conn.execute(TRUNCATE_SQL)
            async with conn.transaction():
                await _seed_sessions(conn, now)
                await _seed_aggregates(conn, now)
                await _seed_bands(conn, now)
            turns = await conn.fetchval("SELECT count(*) FROM turns")
            sessions = await conn.fetchval("SELECT count(*) FROM sessions")
        logger.info("Seeded %s sessions / %s turns", sessions, turns)
    finally:
        await close_pool(pool)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="truncate learner tables before seeding (repeatable reseeds)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(amain(args.reset)))


if __name__ == "__main__":
    main()
