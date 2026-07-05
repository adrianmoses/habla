"""VocabularyRepo — lemmatize + upsert."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg

from hable_ya.learner.vocabulary import VocabularyRepo


async def test_record_extracts_content_lemmas(
    clean_learner_state: asyncpg.Pool,
) -> None:
    """Content-word lemmas (NOUN/VERB/ADJ/AUX/PROPN) land in vocabulary_items.

    The ES small model's POS tagging is imperfect (e.g. `como` in "yo como …"
    is sometimes SCONJ rather than VERB). The assertion set uses utterances
    where the tagging is stable: `quiero comer manzanas` → {querer, comer,
    manzana}, with `manzanas todos los días` pulling `día` too.
    """
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    utterance = "quiero comer manzanas todos los días"
    async with clean_learner_state.acquire() as conn:
        async with conn.transaction():
            lemmas = await VocabularyRepo.record(conn, utterance=utterance, at=at)
    assert {"querer", "comer", "manzana", "día"} <= set(lemmas)

    async with clean_learner_state.acquire() as conn:
        rows = await conn.fetch(
            "SELECT lemma, production_count FROM vocabulary_items ORDER BY lemma"
        )
    present = {r["lemma"]: r["production_count"] for r in rows}
    for lemma in ("querer", "comer", "manzana", "día"):
        assert lemma in present
        assert present[lemma] == 1


async def test_repeat_call_increments_count_and_updates_last_seen(
    clean_learner_state: asyncpg.Pool,
) -> None:
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    utterance = "quiero comer"
    async with clean_learner_state.acquire() as conn:
        async with conn.transaction():
            await VocabularyRepo.record(conn, utterance=utterance, at=base)
        async with conn.transaction():
            await VocabularyRepo.record(
                conn, utterance=utterance, at=base + timedelta(minutes=5)
            )
        row = await conn.fetchrow(
            "SELECT production_count, first_seen_at, last_seen_at "
            "FROM vocabulary_items WHERE lemma = 'comer'"
        )
    assert row is not None
    assert row["production_count"] == 2
    assert row["first_seen_at"] == base
    assert row["last_seen_at"] == base + timedelta(minutes=5)


async def test_top_recent_orders_by_last_seen(
    clean_learner_state: asyncpg.Pool,
) -> None:
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_learner_state.acquire() as conn:
        async with conn.transaction():
            await VocabularyRepo.record(
                conn, utterance="quiero comer manzanas", at=base
            )
        async with conn.transaction():
            await VocabularyRepo.record(
                conn,
                utterance="prefiero beber agua",
                at=base + timedelta(minutes=10),
            )
        top = await VocabularyRepo.top_recent(conn, limit=2)
    # Two most recently seen lemmas come from the second utterance.
    assert set(top) <= {"preferir", "beber", "agua"}
    assert len(top) == 2


async def test_empty_utterance_returns_empty(clean_learner_state: asyncpg.Pool) -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    async with clean_learner_state.acquire() as conn:
        async with conn.transaction():
            lemmas = await VocabularyRepo.record(conn, utterance="", at=at)
    assert lemmas == []
