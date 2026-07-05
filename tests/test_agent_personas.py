"""Persona schema + loader tests (no network, no DB)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.agent.personas.schema import (
    ALLOWED_ERROR_PATTERNS,
    Persona,
    load_personas,
)
from eval.fixtures.schema import LearnerProfile, SystemParams, Theme
from finetune.format import render_system_prompt
from hable_ya.learner.profile import LearnerProfileSnapshot, snapshot_to_profile

PERSONAS_DIR = Path(__file__).resolve().parents[1] / "eval" / "agent" / "personas"


def _minimal_persona_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "test_persona",
        "cefr_band": "A1",
        "scenario_domain": "pedir un café",
        "error_patterns": ["ser_estar"],
        "L1_reliance": 0.5,
        "fluency_signal": "weak",
    }
    base.update(overrides)
    return base


def test_persona_validates_minimal_payload() -> None:
    persona = Persona.model_validate(_minimal_persona_payload())
    assert persona.id == "test_persona"
    assert persona.turn_budget == 12  # default applies


def test_unknown_scenario_domain_for_band_fails() -> None:
    payload = _minimal_persona_payload(scenario_domain="not_a_real_theme")
    with pytest.raises(ValidationError) as ctx:
        Persona.model_validate(payload)
    assert "scenario_domain" in str(ctx.value)


def test_scenario_domain_in_wrong_band_fails() -> None:
    # 'tu vida hace diez años' is a B1 theme, not A1
    payload = _minimal_persona_payload(
        cefr_band="A1", scenario_domain="tu vida hace diez años"
    )
    with pytest.raises(ValidationError):
        Persona.model_validate(payload)


def test_unknown_error_pattern_fails() -> None:
    payload = _minimal_persona_payload(error_patterns=["fake_category"])
    with pytest.raises(ValidationError) as ctx:
        Persona.model_validate(payload)
    assert "fake_category" in str(ctx.value)


def test_extra_fields_rejected() -> None:
    payload = _minimal_persona_payload(extra_field="x")
    with pytest.raises(ValidationError):
        Persona.model_validate(payload)


def test_load_personas_reads_directory(tmp_path: Path) -> None:
    (tmp_path / "p1.json").write_text(
        json.dumps(_minimal_persona_payload(id="p1"))
    )
    (tmp_path / "p2.json").write_text(
        json.dumps(_minimal_persona_payload(id="p2", cefr_band="A2",
                                            scenario_domain="en el restaurante",
                                            error_patterns=["gender_agreement"]))
    )
    personas = load_personas(tmp_path)
    assert [p.id for p in personas] == ["p1", "p2"]


def test_load_authored_smoke_personas() -> None:
    personas = load_personas(PERSONAS_DIR)
    ids = [p.id for p in personas]
    # 3 hand-authored smoke personas, one per band A1/A2/B1.
    assert len(personas) >= 3
    assert "a1_ser_estar_cafeteria" in ids
    assert "a2_gender_agreement_restaurante" in ids
    assert "b1_preterite_imperfect_recuerdos" in ids


def test_load_personas_fails_on_first_invalid_file(tmp_path: Path) -> None:
    (tmp_path / "good.json").write_text(json.dumps(_minimal_persona_payload()))
    (tmp_path / "bad.json").write_text(json.dumps({"id": "bad"}))
    with pytest.raises(ValidationError):
        load_personas(tmp_path)


def test_allowed_error_patterns_covers_smoke_personas() -> None:
    personas = load_personas(PERSONAS_DIR)
    for p in personas:
        for cat in p.error_patterns:
            assert cat in ALLOWED_ERROR_PATTERNS


def test_snapshot_to_profile_composes_with_render_system_prompt() -> None:
    """The eval path renders the same prompt the runtime would."""
    snapshot = LearnerProfileSnapshot(
        band="B1",
        sessions_completed=4,
        l1_reliance=0.3,
        speech_fluency=0.6,
        error_patterns=["ser_estar"],
        vocab_strengths=["caminar", "ciudad"],
    )
    # Spec 049: is_calibrated is now an explicit parameter (sourced from
    # band_history in the runtime). Eval-accumulator path defaults to False;
    # pass True here to exercise the calibrated rendering path.
    profile = snapshot_to_profile(snapshot, is_calibrated=True)
    assert isinstance(profile, LearnerProfile)
    assert profile.is_calibrated is True
    assert profile.error_patterns == ["ser_estar"]

    theme = Theme(
        domain="tu vida hace diez años",
        prompt="Habla con el estudiante sobre cómo era su vida hace diez años.",
        target_structures=["pretérito", "imperfecto"],
    )
    rendered = render_system_prompt(
        SystemParams(profile=profile, theme=theme), band="B1"
    )
    assert isinstance(rendered, str)
    assert rendered.strip()
