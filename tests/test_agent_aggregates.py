"""compute_agent_aggregates shape tests (no network)."""

from __future__ import annotations

import pytest

from eval.agent.opus_judge import SessionVerdict
from eval.agent.run_agent_eval import _filter_personas, compute_agent_aggregates
from eval.agent.types import SessionRecord


def _verdict(score: int, stop: str = "budget_reached") -> SessionVerdict:
    return SessionVerdict.model_validate(
        {
            "pedagogical_flow": score,
            "level_consistency": score,
            "recast_naturalness": score,
            "learner_production_space": score,
            "coherence": score,
            "rationale": {
                "pedagogical_flow": "ok",
                "level_consistency": "ok",
                "recast_naturalness": "ok",
                "learner_production_space": "ok",
                "coherence": "ok",
            },
            "stop_reason": stop,
        }
    )


def _session(
    persona_id: str,
    band: str,
    error_patterns: list[str],
    score: int,
    stop: str = "budget_reached",
) -> SessionRecord:
    return SessionRecord.model_validate(
        {
            "persona_id": persona_id,
            "cefr_band": band,
            "scenario_domain": "n/a",
            "error_patterns": error_patterns,
            "transcript": [],
            "turn_records": [],
            "verdict": _verdict(score, stop=stop).model_dump(),
            "model_label": "test",
            "elapsed_s": 1.0,
        }
    )


def test_empty_returns_empty_dict() -> None:
    assert compute_agent_aggregates([]) == {}


def test_overall_and_by_dimension_means() -> None:
    sessions = [
        _session("a", "A1", ["ser_estar"], 4),
        _session("b", "A2", ["gender_agreement"], 3),
        _session("c", "B1", ["preterite_imperfect"], 5),
    ]
    agg = compute_agent_aggregates(sessions)
    assert agg["overall"]["n"] == 3
    assert agg["overall"]["mean"] == pytest.approx(4.0)  # (4+3+5)/3
    for dim in (
        "pedagogical_flow",
        "level_consistency",
        "recast_naturalness",
        "learner_production_space",
        "coherence",
    ):
        assert agg["by_dimension"][dim]["mean"] == pytest.approx(4.0)


def test_by_band_groups_correctly() -> None:
    sessions = [
        _session("a1", "A1", ["ser_estar"], 4),
        _session("a1b", "A1", ["ser_estar"], 2),
        _session("b1", "B1", ["preterite_imperfect"], 5),
    ]
    agg = compute_agent_aggregates(sessions)
    assert agg["by_band"]["A1"]["n"] == 2
    assert agg["by_band"]["A1"]["overall_mean"] == pytest.approx(3.0)
    assert agg["by_band"]["B1"]["n"] == 1
    assert agg["by_band"]["B1"]["overall_mean"] == pytest.approx(5.0)


def test_by_error_pattern_one_session_can_count_under_multiple() -> None:
    sessions = [
        _session("multi", "B1", ["ser_estar", "preterite_imperfect"], 4),
        _session("se", "A1", ["ser_estar"], 2),
    ]
    agg = compute_agent_aggregates(sessions)
    assert agg["by_error_pattern"]["ser_estar"]["n"] == 2
    assert agg["by_error_pattern"]["ser_estar"]["overall_mean"] == pytest.approx(3.0)
    assert agg["by_error_pattern"]["preterite_imperfect"]["n"] == 1
    assert agg["by_error_pattern"]["preterite_imperfect"]["overall_mean"] == 4.0


def test_stop_reasons_counted() -> None:
    sessions = [
        _session("a", "A1", ["ser_estar"], 4, stop="budget_reached"),
        _session("b", "A2", ["gender_agreement"], 3, stop="agent_derailed"),
        _session("c", "A2", ["ser_estar"], 3, stop="budget_reached"),
    ]
    agg = compute_agent_aggregates(sessions)
    assert agg["stop_reasons"]["budget_reached"] == 2
    assert agg["stop_reasons"]["agent_derailed"] == 1


# ---------- _filter_personas ----------


def _persona(pid: str):
    from eval.agent.personas.schema import Persona

    return Persona.model_validate(
        {
            "id": pid,
            "cefr_band": "A1",
            "scenario_domain": "pedir un café",
            "error_patterns": ["ser_estar"],
            "L1_reliance": 0.5,
            "fluency_signal": "weak",
        }
    )


def test_filter_personas_glob() -> None:
    personas = [_persona(p) for p in ["a1_x", "a1_y", "a2_z"]]
    selected = _filter_personas(personas, "a1_*")
    assert [p.id for p in selected] == ["a1_x", "a1_y"]


def test_filter_personas_comma_list() -> None:
    personas = [_persona(p) for p in ["a1_x", "a1_y", "a2_z"]]
    selected = _filter_personas(personas, "a1_x,a2_z")
    assert [p.id for p in selected] == ["a1_x", "a2_z"]


def test_filter_personas_glob_plus_exact() -> None:
    personas = [_persona(p) for p in ["a1_x", "a2_y", "b1_z"]]
    selected = _filter_personas(personas, "a1_*,b1_z")
    assert [p.id for p in selected] == ["a1_x", "b1_z"]
