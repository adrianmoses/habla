"""ProfileAccumulator tests, including the DB-backed equivalence guard."""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from eval.agent.accumulator import ProfileAccumulator
from eval.agent.personas.schema import Persona
from eval.agent.types import TurnRecord
from eval.fixtures.schema import FluencySignal
from hable_ya.learner.profile import LearnerProfileRepo


def _persona(band: str = "A2") -> Persona:
    return Persona.model_validate(
        {
            "id": "test_acc",
            "cefr_band": band,
            "scenario_domain": (
                "pedir un café" if band == "A1" else "en el restaurante"
            ),
            "error_patterns": ["ser_estar"],
            "L1_reliance": 0.3,
            "fluency_signal": "moderate",
        }
    )


def test_neutral_snapshot_when_no_turns_ingested() -> None:
    acc = ProfileAccumulator(_persona())
    snapshot = acc.snapshot()
    assert snapshot.band == "A2"
    assert snapshot.sessions_completed == 0
    assert snapshot.l1_reliance == 0.5
    assert snapshot.speech_fluency == 0.5
    assert snapshot.error_patterns == []
    assert snapshot.vocab_strengths == []
    assert acc.turns_ingested == 0


def test_ingest_updates_rolling_means() -> None:
    acc = ProfileAccumulator(_persona())
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    rows: list[tuple[FluencySignal, bool]] = [
        ("weak", True),
        ("weak", False),
        ("moderate", True),
        ("strong", False),
        ("strong", False),
    ]
    for i, (fluency, l1) in enumerate(rows):
        acc.ingest(
            TurnRecord(fluency_signal=fluency, L1_used=l1),
            observed_at=base.replace(minute=i),
        )

    snapshot = acc.snapshot()
    assert snapshot.l1_reliance == pytest.approx(2 / 5)
    assert snapshot.speech_fluency == pytest.approx(
        (0.3 + 0.3 + 0.6 + 0.9 + 0.9) / 5
    )
    assert acc.turns_ingested == 5


def test_window_evicts_oldest_turns() -> None:
    acc = ProfileAccumulator(_persona(), window_turns=3)
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    # First turn (will be evicted): strong + no L1.
    acc.ingest(
        TurnRecord(fluency_signal="strong", L1_used=False),
        observed_at=base,
    )
    # Three more turns inside the window: weak + L1.
    for i in range(3):
        acc.ingest(
            TurnRecord(fluency_signal="weak", L1_used=True),
            observed_at=base.replace(minute=i + 1),
        )

    snapshot = acc.snapshot()
    assert snapshot.l1_reliance == pytest.approx(1.0)
    assert snapshot.speech_fluency == pytest.approx(0.3)


def test_error_counter_orders_top_n_by_count() -> None:
    acc = ProfileAccumulator(_persona(), top_errors=3)
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    # ser_estar=5, prepositions=4, agreement=3, tense=1
    pattern = ["ser_estar"] * 5 + ["prepositions"] * 4 + ["agreement"] * 3 + ["tense"]
    for cat in pattern:
        acc.ingest(
            TurnRecord(
                fluency_signal="moderate", L1_used=False, error_categories=[cat]
            ),
            observed_at=at,
        )
    snapshot = acc.snapshot()
    assert snapshot.error_patterns == ["ser_estar", "prepositions", "agreement"]


def test_vocab_last_seen_tracks_most_recent() -> None:
    acc = ProfileAccumulator(_persona(), top_vocab=3)
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    for i, lemma in enumerate(["uno", "dos", "tres", "cuatro", "cinco", "seis"]):
        acc.ingest(
            TurnRecord(
                fluency_signal="moderate",
                L1_used=False,
                vocab_lemmas=[lemma],
            ),
            observed_at=base.replace(minute=i),
        )
    snapshot = acc.snapshot()
    assert snapshot.vocab_strengths == ["seis", "cinco", "cuatro"]


def test_repeated_lemma_updates_last_seen() -> None:
    acc = ProfileAccumulator(_persona(), top_vocab=2)
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    acc.ingest(
        TurnRecord(fluency_signal="moderate", L1_used=False, vocab_lemmas=["alpha"]),
        observed_at=base,
    )
    acc.ingest(
        TurnRecord(fluency_signal="moderate", L1_used=False, vocab_lemmas=["beta"]),
        observed_at=base.replace(minute=1),
    )
    # `alpha` reappears later; should now lead.
    acc.ingest(
        TurnRecord(fluency_signal="moderate", L1_used=False, vocab_lemmas=["alpha"]),
        observed_at=base.replace(minute=2),
    )
    snapshot = acc.snapshot()
    assert snapshot.vocab_strengths == ["alpha", "beta"]


def test_empty_error_categories_does_not_pollute_counter() -> None:
    acc = ProfileAccumulator(_persona())
    acc.ingest(
        TurnRecord(fluency_signal="moderate", L1_used=False),
        observed_at=datetime.now(UTC),
    )
    snapshot = acc.snapshot()
    assert snapshot.error_patterns == []
    assert acc.turns_ingested == 1


# ---------- DB-backed equivalence guard ----------


async def test_accumulator_matches_repo_for_same_log_turn_sequence(
    clean_learner_state: asyncpg.Pool,
) -> None:
    """The whole point of compute_snapshot: eval and repo agree.

    Inserts the same observations into both Postgres (via the same SQL
    the production ingest path uses) and the in-memory accumulator, then
    asserts the two snapshots are field-for-field identical.
    """
    persona = _persona()
    acc = ProfileAccumulator(
        persona, window_turns=20, top_errors=3, top_vocab=3
    )
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    timeline: list[tuple[datetime, FluencySignal, bool, list[str], list[str]]] = [
        (base.replace(minute=0), "weak", True, ["ser_estar"], ["café", "querer"]),
        (base.replace(minute=1), "moderate", False, ["ser_estar"], ["mesa"]),
        (
            base.replace(minute=2),
            "moderate",
            False,
            ["gender_agreement"],
            ["mesa", "grande"],
        ),
        (base.replace(minute=3), "strong", False, [], ["plato"]),
    ]

    # Feed the accumulator.
    for at, fluency, l1, errors, lemmas in timeline:
        acc.ingest(
            TurnRecord(
                fluency_signal=fluency,
                L1_used=l1,
                error_categories=errors,
                vocab_lemmas=lemmas,
            ),
            observed_at=at,
        )

    # Mirror the same observations into Postgres using the same shape the
    # production ingest path produces. We hit the tables directly here
    # rather than going through TurnIngestService — the equivalence we
    # care about is between compute_snapshot's two callers, not between
    # the ingest service and the accumulator.
    async with clean_learner_state.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (session_id, band_at_start) VALUES ('eq', 'A2')"
        )
        for at, fluency, l1, errors, lemmas in timeline:
            await conn.execute(
                """
                INSERT INTO turns
                  (session_id, timestamp, learner_utterance, fluency_signal, L1_used)
                VALUES ('eq', $1, $2, $3, $4)
                """,
                at,
                "x",
                fluency,
                l1,
            )
            for cat in errors:
                await conn.execute(
                    """
                    INSERT INTO error_counts (category, count, last_seen_at)
                    VALUES ($1, 1, $2)
                    ON CONFLICT (category) DO UPDATE SET
                        count = error_counts.count + 1,
                        last_seen_at = EXCLUDED.last_seen_at
                    """,
                    cat,
                    at,
                )
            for lemma in lemmas:
                await conn.execute(
                    """
                    INSERT INTO vocabulary_items
                      (lemma, sample_form, production_count,
                       first_seen_at, last_seen_at)
                    VALUES ($1, $1, 1, $2, $2)
                    ON CONFLICT (lemma) DO UPDATE SET
                        production_count = vocabulary_items.production_count + 1,
                        last_seen_at = EXCLUDED.last_seen_at
                    """,
                    lemma,
                    at,
                )

    repo = LearnerProfileRepo(clean_learner_state)
    repo_snapshot = await repo.get(window_turns=20, top_errors=3, top_vocab=3)
    acc_snapshot = acc.snapshot()
    assert repo_snapshot == acc_snapshot
