"""Pure-function tests for ``hable_ya.learner.leveling.policy.evaluate_leveling``.

Covers: stable-at-current; promote at K=3; demote at K=4 only when the
rolling mean crosses one full band-width (no demotion-clock-start on
borderline); floor (A1) and ceiling (C1) no-ops; mixed sequence reset.
"""

from __future__ import annotations

import pytest

from eval.fixtures.schema import CEFRBand
from hable_ya.learner.leveling.policy import (
    LevelingDecision,
    bucket_band,
    evaluate_leveling,
)


def test_empty_window_returns_no_data_stable() -> None:
    decision = evaluate_leveling(
        current_band="A2",
        recent_turn_bands=[],
        stable_sessions=0,
    )
    assert decision == LevelingDecision(
        new_band="A2",
        reason="stable",
        signals={"reason": "no_data"},
    )


def test_target_equals_current_is_stable() -> None:
    decision = evaluate_leveling(
        current_band="A2",
        recent_turn_bands=["A2", "A2", "A2"],
        stable_sessions=0,
    )
    assert decision.reason == "stable"
    assert decision.new_band == "A2"
    assert decision.signals["toward"] == "A2"


def test_promote_does_not_fire_below_K() -> None:
    # K-1 sessions accumulated. Current decision is stable, toward target.
    decision = evaluate_leveling(
        current_band="A2",
        recent_turn_bands=["B1", "B1", "B1"],
        stable_sessions=1,  # one prior promote-target session
        promote_consecutive=3,
    )
    assert decision.reason == "stable"
    assert decision.signals["toward"] == "B1"


def test_promote_fires_at_K() -> None:
    decision = evaluate_leveling(
        current_band="A2",
        recent_turn_bands=["B1", "B1", "B1"],
        stable_sessions=2,  # this is the K-th evaluation
        promote_consecutive=3,
    )
    assert decision.reason == "auto_promote"
    assert decision.new_band == "B1"


def test_demote_borderline_does_not_start_clock() -> None:
    # current=B1 (center 0.5). Mean barely below the 0.40 boundary →
    # bucket_band returns A2, but mean > A2 center (0.30). So borderline.
    bands: list[CEFRBand] = ["B1", "B1", "A2", "A2"]
    # mean = (0.5+0.5+0.3+0.3)/4 = 0.4 → bucket_band(0.4) returns... let's
    # confirm: BAND_BUCKETS has (0.40, "A2"), so 0.4 < 0.40 is False; 0.4 <
    # 0.60 is True → bucket = B1, target == current → stable. Need a mean
    # strictly below 0.40 but above A2 center 0.30.
    bands = ["B1", "A2", "A2", "A2"]  # mean = (0.5+0.3+0.3+0.3)/4 = 0.35
    decision = evaluate_leveling(
        current_band="B1",
        recent_turn_bands=bands,
        stable_sessions=3,  # would otherwise hit K=4 demote
        demote_consecutive=4,
    )
    assert decision.reason == "stable"
    assert decision.signals["toward"] == "borderline"


def test_demote_one_band_fires_when_mean_at_target_center() -> None:
    """B1 → A2 demote: mean ≤ A2 center (0.30) triggers non-borderline."""
    bands: list[CEFRBand] = ["A2", "A2", "A2", "A1"]
    # mean = (0.3 + 0.3 + 0.3 + 0.1) / 4 = 0.25 ≤ 0.30 (A2 center)
    decision = evaluate_leveling(
        current_band="B1",
        recent_turn_bands=bands,
        stable_sessions=3,
        demote_consecutive=4,
    )
    assert decision.reason == "auto_demote"
    assert decision.new_band == "A2"


def test_demote_two_bands_fires_when_mean_at_a1_center() -> None:
    """B1 → A1 demote: bucket_band lands on A1 and mean ≤ A1 center (0.1)."""
    bands: list[CEFRBand] = ["A1", "A1", "A1", "A1"]
    # mean = 0.1 == A1 center → not borderline (mean > center is False).
    decision = evaluate_leveling(
        current_band="B1",
        recent_turn_bands=bands,
        stable_sessions=3,
        demote_consecutive=4,
    )
    assert decision.reason == "auto_demote"
    assert decision.new_band == "A1"


def test_demote_does_not_fire_below_K() -> None:
    bands: list[CEFRBand] = ["A1", "A1", "A1"]  # mean = 0.1
    decision = evaluate_leveling(
        current_band="B1",
        recent_turn_bands=bands,
        stable_sessions=2,  # K-2; need 4 total demote-toward sessions
        demote_consecutive=4,
    )
    assert decision.reason == "stable"
    assert decision.new_band == "B1"


def test_floor_a1_target_lower_is_no_op() -> None:
    # current=A1 already floors out — target can't be lower than A1
    # because bucket_band returns A1 for any mean below 0.20. evaluate
    # returns stable since target == current.
    bands: list[CEFRBand] = ["A1", "A1", "A1"]
    decision = evaluate_leveling(
        current_band="A1",
        recent_turn_bands=bands,
        stable_sessions=10,
    )
    assert decision.new_band == "A1"
    assert decision.reason == "stable"


def test_ceiling_c1_target_higher_is_no_op() -> None:
    bands: list[CEFRBand] = ["C1", "C1", "C1"]
    decision = evaluate_leveling(
        current_band="C1",
        recent_turn_bands=bands,
        stable_sessions=10,
    )
    assert decision.new_band == "C1"
    assert decision.reason == "stable"


def test_mixed_sequence_does_not_promote_when_streak_breaks() -> None:
    """2 promote-target + 1 stable-at-current + 1 promote → does NOT promote.

    The pure function takes ``stable_sessions`` directly; the LevelingService
    is the bookkeeper that resets the counter on stable-at-current. Here we
    simulate the counter the service would have written: it's 0 (was reset
    by the 1-stable session), so the K-th promote-target session gets
    treated as the FIRST in the streak.
    """
    bands: list[CEFRBand] = ["B1", "B1", "B1"]
    decision = evaluate_leveling(
        current_band="A2",
        recent_turn_bands=bands,
        stable_sessions=0,  # streak was reset by intervening stable session
        promote_consecutive=3,
    )
    assert decision.reason == "stable"
    assert decision.signals["toward"] == "B1"


def test_evaluate_leveling_is_deterministic() -> None:
    bands: list[CEFRBand] = ["B1", "A2", "B1", "B2", "B1"]
    first = evaluate_leveling(
        current_band="A2",
        recent_turn_bands=bands,
        stable_sessions=2,
    )
    second = evaluate_leveling(
        current_band="A2",
        recent_turn_bands=bands,
        stable_sessions=2,
    )
    assert first == second


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, "A1"),
        (0.19, "A1"),
        (0.20, "A2"),
        (0.39, "A2"),
        (0.40, "B1"),
        (0.59, "B1"),
        (0.60, "B2"),
        (0.79, "B2"),
        (0.80, "C1"),
        (0.95, "C1"),
    ],
)
def test_bucket_band_boundaries(score: float, expected: CEFRBand) -> None:
    assert bucket_band(score) == expected
