"""Pure-function tests for ``hable_ya.learner.leveling.policy.place_band``.

No DB. Asserts modal selection, tie-break to the higher band, floor
clamping, and the abstain-when-too-few-valid posture.
"""

from __future__ import annotations

import pytest

from eval.fixtures.schema import CEFRBand
from hable_ya.learner.leveling.policy import place_band


def test_place_band_returns_none_when_too_few_valid_turns() -> None:
    # Two valid + two None < min_valid_turns=3.
    decision = place_band([None, "A2", None, "A2"], min_valid_turns=3)
    assert decision is None


def test_place_band_returns_none_on_all_none() -> None:
    decision = place_band([None, None, None, None], min_valid_turns=3)
    assert decision is None


def test_place_band_picks_modal_band() -> None:
    decision = place_band(["A1", "A1", "A2", "A1"], floor_band="A1")
    assert decision is not None
    assert decision.band == "A1"
    assert decision.signals["modal_band"] == "A1"
    assert decision.signals["valid_turns"] == 4


def test_place_band_tie_break_takes_higher_band() -> None:
    # Two A2 + two B1 → tie. Tie-break to higher band.
    decision = place_band(["A2", "A2", "B1", "B1"], floor_band="A1")
    assert decision is not None
    assert decision.band == "B1"
    assert decision.signals["modal_band"] == "B1"


def test_place_band_above_floor_returns_modal() -> None:
    decision = place_band(["C1", "C1", "C1", "C1"], floor_band="A2")
    assert decision is not None
    assert decision.band == "C1"
    assert decision.signals["floor_applied"] is False


def test_place_band_below_floor_clamps_to_floor() -> None:
    decision = place_band(["A1", "A1", "A1", "A1"], floor_band="A2")
    assert decision is not None
    assert decision.band == "A2"
    assert decision.signals["modal_band"] == "A1"
    assert decision.signals["floor_applied"] is True


def test_place_band_drops_none_from_count() -> None:
    decision = place_band(
        ["B1", None, "B1", None, "B1"],
        min_valid_turns=3,
        floor_band="A1",
    )
    assert decision is not None
    assert decision.band == "B1"
    assert decision.signals["valid_turns"] == 3
    assert decision.signals["total_turns"] == 5


def test_place_band_is_deterministic() -> None:
    bands: list[CEFRBand | None] = ["A2", "B1", "A2", "B1", None, "A2"]
    first = place_band(bands, floor_band="A1")
    second = place_band(bands, floor_band="A1")
    assert first == second


def test_place_band_signals_counts_only_valid() -> None:
    decision = place_band(
        ["A1", None, "A2", "A1"],
        min_valid_turns=3,
        floor_band="A1",
    )
    assert decision is not None
    assert decision.signals["counts"] == {"A1": 2, "A2": 1}


@pytest.mark.parametrize(
    "bands,expected",
    [
        # Three A1, one B2: modal = A1, lifted to A2 floor.
        (["A1", "A1", "A1", "B2"], "A2"),
        # Mixed with B1 majority.
        (["B1", "A2", "B1", "B1"], "B1"),
        # All C1, floor irrelevant.
        (["C1", "C1", "C1"], "C1"),
    ],
)
def test_place_band_table(
    bands: list[CEFRBand | None], expected: CEFRBand
) -> None:
    decision = place_band(bands, floor_band="A2", min_valid_turns=3)
    assert decision is not None
    assert decision.band == expected
