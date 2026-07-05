"""Tests for the shared compute_snapshot pure function.

These tests do not touch the database. They cover the rolling-mean and
top-N rules in isolation. The DB-backed equivalence test in
`test_learner_profile.py` confirms the repo wires the same logic correctly.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest

from hable_ya.learner.aggregations import (
    LearnerProfileSnapshot,
    compute_snapshot,
)


def test_empty_inputs_return_neutral_defaults() -> None:
    snapshot = compute_snapshot(
        band="A2",
        sessions_completed=0,
        l1_used_flags=[],
        fluency_signals=[],
        error_counter={},
        error_last_seen={},
        vocab_last_seen={},
        top_errors=3,
        top_vocab=5,
    )
    assert snapshot == LearnerProfileSnapshot(
        band="A2",
        sessions_completed=0,
        l1_reliance=0.5,
        speech_fluency=0.5,
        error_patterns=[],
        vocab_strengths=[],
    )


def test_rolling_means_average_over_window() -> None:
    # Mirrors test_rolling_means_reflect_recent_turns: 5 turns, 2 with L1,
    # fluency = (0.3, 0.3, 0.6, 0.9, 0.9) / 5.
    snapshot = compute_snapshot(
        band="B1",
        sessions_completed=4,
        l1_used_flags=[True, False, True, False, False],
        fluency_signals=["weak", "weak", "moderate", "strong", "strong"],
        error_counter={},
        error_last_seen={},
        vocab_last_seen={},
        top_errors=3,
        top_vocab=5,
    )
    assert snapshot.l1_reliance == pytest.approx(2 / 5)
    assert snapshot.speech_fluency == pytest.approx((0.3 + 0.3 + 0.6 + 0.9 + 0.9) / 5)
    assert snapshot.band == "B1"
    assert snapshot.sessions_completed == 4


def test_top_errors_order_by_count_descending() -> None:
    at = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    snapshot = compute_snapshot(
        band="A2",
        sessions_completed=0,
        l1_used_flags=[],
        fluency_signals=[],
        error_counter=Counter(
            {"ser_estar": 5, "agreement": 3, "tense": 1, "prepositions": 4}
        ),
        error_last_seen={
            "ser_estar": at,
            "agreement": at,
            "tense": at,
            "prepositions": at,
        },
        vocab_last_seen={},
        top_errors=3,
        top_vocab=5,
    )
    assert snapshot.error_patterns == ["ser_estar", "prepositions", "agreement"]


def test_top_errors_tiebreak_by_last_seen_descending() -> None:
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    snapshot = compute_snapshot(
        band="A2",
        sessions_completed=0,
        l1_used_flags=[],
        fluency_signals=[],
        # Same count for all three; last_seen ordering decides.
        error_counter={"a": 2, "b": 2, "c": 2},
        error_last_seen={
            "a": base.replace(minute=0),
            "b": base.replace(minute=2),
            "c": base.replace(minute=1),
        },
        vocab_last_seen={},
        top_errors=3,
        top_vocab=5,
    )
    assert snapshot.error_patterns == ["b", "c", "a"]


def test_top_vocab_order_by_last_seen_descending() -> None:
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    snapshot = compute_snapshot(
        band="A2",
        sessions_completed=0,
        l1_used_flags=[],
        fluency_signals=[],
        error_counter={},
        error_last_seen={},
        vocab_last_seen={
            lemma: base.replace(minute=i)
            for i, lemma in enumerate(["uno", "dos", "tres", "cuatro", "cinco", "seis"])
        },
        top_errors=3,
        top_vocab=3,
    )
    assert snapshot.vocab_strengths == ["seis", "cinco", "cuatro"]


def test_truncates_to_top_n_limits() -> None:
    base = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    snapshot = compute_snapshot(
        band="A2",
        sessions_completed=0,
        l1_used_flags=[],
        fluency_signals=[],
        error_counter={"a": 5, "b": 4, "c": 3, "d": 2, "e": 1},
        error_last_seen={k: base for k in "abcde"},
        vocab_last_seen={
            lemma: base.replace(minute=i)
            for i, lemma in enumerate(["x", "y", "z"])
        },
        top_errors=2,
        top_vocab=2,
    )
    assert snapshot.error_patterns == ["a", "b"]
    assert snapshot.vocab_strengths == ["z", "y"]


def test_does_not_re_window_l1_or_fluency() -> None:
    # Caller is expected to trim. compute_snapshot takes the whole sequence.
    snapshot = compute_snapshot(
        band="A2",
        sessions_completed=0,
        l1_used_flags=[True] * 100,
        fluency_signals=["strong"] * 100,
        error_counter={},
        error_last_seen={},
        vocab_last_seen={},
        top_errors=3,
        top_vocab=5,
    )
    assert snapshot.l1_reliance == pytest.approx(1.0)
    assert snapshot.speech_fluency == pytest.approx(0.9)
