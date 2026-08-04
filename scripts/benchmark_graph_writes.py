"""What the per-turn AGE graph writes actually cost (spec #022).

#022 asks whether the knowledge graph is load-bearing. It is written on every
turn and read by nothing, so before deciding what to do about that, the cost
side of the ledger needs a number rather than an intuition — specifically for
Open Question 2: do the graph writes stay inside the ingest transaction, where
a cypher failure can roll back a turn's real relational state?

For a corpus of representative turn observations, over N iterations, this times
the same work `TurnIngestService.ingest` does, split in two:

  - relational : turn row + error_observations/error_counts + vocabulary_items
  - graph      : the cypher upserts (`upsert_error_pattern`, `upsert_vocab`)

Both run inside one transaction per iteration, exactly as `ingest` composes
them, so the split is measured under the real locking and round-trip
conditions rather than in isolation.

Also reports **cypher round trips per turn**, which is arithmetic rather than a
measurement: each `upsert_vocab` and each `upsert_error_pattern` issues two
`_run_cypher` calls, so a turn costs `2 x distinct_categories + 2 x lemmas`.

Dev-only, and cheap: no provider is involved, so unlike
`scripts/benchmark_latency.py` this needs no API keys — just a local AGE
instance.

**DESTRUCTIVE.** To measure steady-state cost without accumulating across
runs, this TRUNCATEs the learner tables and strips the graph before starting —
the same statements `scripts/seed_dev_learner.py --reset` and the
`clean_learner_state` fixture use. Point it at a scratch database, and
re-seed afterwards with `uv run python scripts/seed_dev_learner.py --reset`.

Run:  docker compose up -d db
      HABLE_YA_DATABASE_URL=postgresql://hable_ya:hable_ya@localhost:5433/hable_ya \
      HABLE_YA_ALLOW_DEFAULT_DB_CREDENTIALS=true \
          uv run python scripts/benchmark_graph_writes.py [--iterations 30] \
              [--output docs/specs/022-knowledge-graph-read/graph-cost.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import load_dotenv

from hable_ya.db import close_pool, open_pool
from hable_ya.learner import graph
from hable_ya.learner.errors import ErrorRepo
from hable_ya.learner.vocabulary import VocabularyRepo
from hable_ya.runtime.latency import STATS_HEADER, LatencyStats, summarize

# Representative learner turns: enough vocabulary to be typical (the spec's
# worked example is ~8 lemmas), one with two error categories, one clean.
CORPUS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "Ayer yo comí una manzana muy grande en el mercado del centro.",
        (("preterite_imperfect", "comí", "comí"), ("gender_agreement", "un", "una")),
    ),
    (
        "Mañana voy a viajar a Madrid con mis amigos para visitar el museo.",
        (("ser_estar", "soy", "estoy"),),
    ),
    (
        "Me gusta mucho cocinar comida española los fines de semana.",
        (),
    ),
)

SESSION_ID = "benchmark-graph-writes"


async def _reset(conn: asyncpg.Connection) -> None:
    """Truncate learner tables and strip the graph — same statements the
    `clean_learner_state` fixture uses, so a run does not accumulate."""
    await conn.execute(
        "TRUNCATE error_observations, error_counts, vocabulary_items, "
        "turns, sessions, band_history RESTART IDENTITY CASCADE"
    )
    await conn.execute(
        f"SELECT * FROM cypher('{graph.GRAPH}', $$ "
        f"MATCH (n) DETACH DELETE n $$) AS (v ag_catalog.agtype)"
    )
    await conn.execute(
        """
        INSERT INTO sessions (session_id, started_at, theme_domain, band_at_start)
        VALUES ($1, now(), 'pedir un café', 'A2')
        ON CONFLICT (session_id) DO NOTHING
        """,
        SESSION_ID,
    )


async def run_benchmark(
    pool: asyncpg.Pool, iterations: int
) -> tuple[dict[str, LatencyStats], dict[str, float]]:
    relational_ms: list[float] = []
    graph_ms: list[float] = []
    round_trips: list[int] = []

    async with pool.acquire() as conn:
        await _reset(conn)
        await graph.ensure_learner_node(conn)

        # Warm-up, discarded: the first `VocabularyRepo.record` loads the
        # es_core_news_sm spaCy model, which costs ~10x a steady-state turn and
        # would otherwise dominate the relational mean. The runtime pays it once
        # at boot, not per turn, so including it would overstate the relational
        # side and understate the graph's share.
        async with conn.transaction():
            warm_id = await conn.fetchval(
                """
                INSERT INTO turns
                    (session_id, timestamp, learner_utterance,
                     fluency_signal, L1_used, cefr_band)
                VALUES ($1, now(), $2, 'moderate', false, 'A2')
                RETURNING id
                """,
                SESSION_ID,
                CORPUS[0][0],
            )
            assert warm_id is not None
            await VocabularyRepo.record(
                conn, utterance=CORPUS[0][0], at=datetime.now(UTC)
            )

        for i in range(iterations):
            utterance, errors = CORPUS[i % len(CORPUS)]
            at = datetime.now(UTC)

            async with conn.transaction():
                t0 = time.perf_counter()
                turn_id = await conn.fetchval(
                    """
                    INSERT INTO turns
                        (session_id, timestamp, learner_utterance,
                         fluency_signal, L1_used, cefr_band)
                    VALUES ($1, $2, $3, 'moderate', false, 'A2')
                    RETURNING id
                    """,
                    SESSION_ID,
                    at,
                    utterance,
                )
                categories = (
                    await ErrorRepo.record(
                        conn,
                        turn_id=turn_id,
                        errors=[
                            {"type": t, "produced_form": p, "target_form": g}
                            for t, p, g in errors
                        ],
                        at=at,
                    )
                    if errors
                    else []
                )
                lemmas = await VocabularyRepo.record(conn, utterance=utterance, at=at)
                t1 = time.perf_counter()

                for category in set(categories):
                    await graph.upsert_error_pattern(conn, category=category, at=at)
                for lemma in lemmas:
                    await graph.upsert_vocab(conn, lemma=lemma, at=at)
                t2 = time.perf_counter()

            relational_ms.append((t1 - t0) * 1000.0)
            graph_ms.append((t2 - t1) * 1000.0)
            # Two _run_cypher calls per upsert, per graph.py.
            round_trips.append(2 * len(set(categories)) + 2 * len(lemmas))

    stats = {"relational": summarize(relational_ms), "graph": summarize(graph_ms)}
    total_p50 = stats["relational"].p50 + stats["graph"].p50
    derived = {
        "graph_share_of_transaction_pct": (
            100.0 * stats["graph"].p50 / total_p50 if total_p50 else 0.0
        ),
        "cypher_round_trips_mean": sum(round_trips) / len(round_trips),
        "cypher_round_trips_max": float(max(round_trips)),
    }
    return stats, derived


def _print_report(stats: dict[str, LatencyStats], derived: dict[str, float]) -> None:
    print("\nPer-turn ingest cost, split (ms)\n")
    print(STATS_HEADER)
    for label in ("relational", "graph"):
        print(stats[label].format_row(label))
    print(
        f"\ngraph share of the ingest transaction (p50): "
        f"{derived['graph_share_of_transaction_pct']:.1f}%"
    )
    print(
        f"cypher round trips per turn: "
        f"mean {derived['cypher_round_trips_mean']:.1f}, "
        f"max {derived['cypher_round_trips_max']:.0f}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Per-turn AGE graph write cost (#022)")
    parser.add_argument("--iterations", type=int, default=30, help="turns to ingest")
    parser.add_argument("--output", type=Path, default=None, help="write raw JSON here")
    args = parser.parse_args()

    load_dotenv()
    pool = await open_pool()
    try:
        stats, derived = await run_benchmark(pool, args.iterations)
    finally:
        await close_pool(pool)

    _print_report(stats, derived)

    if args.output:
        payload: dict[str, Any] = {
            "spec": "022-knowledge-graph-read",
            "iterations": args.iterations,
            "corpus_size": len(CORPUS),
            "stages_ms": {k: vars(v) for k, v in stats.items()},
            "derived": derived,
        }
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
