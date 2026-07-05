"""Tests for the strict universal_checks added in Phase 2."""

from __future__ import annotations

from typing import Any

from eval.fixtures.schema import Fixture, parse_fixture
from scripts.fixtures.validate_fixtures import universal_checks, validate_one


def _base_fixture_dict() -> dict[str, Any]:
    """Construct a minimal valid standard fixture (single ser_estar error)."""
    return {
        "id": "single_error_recast_A1_test_001",
        "type": "standard",
        "system_params": {
            "profile": {
                "production_level": 0.15,
                "L1_reliance": 0.4,
                "speech_fluency": 0.3,
                "is_calibrated": True,
                "sessions_completed": 3,
                "vocab_strengths": [],
                "error_patterns": [],
            },
            "theme": {
                "domain": "city_life",
                "prompt": "Talk about your neighbourhood.",
                "target_structures": [],
            },
        },
        "conversation": [
            {"role": "assistant", "content": "Hola, ¿dónde vives?"},
            {"role": "user", "content": "El parque es cerca de mi casa."},
        ],
        "expected": {
            "response_text": "Ah, el parque está cerca de tu casa. ¿Vas mucho?",
            "recast_form": "está cerca",
            "tool_calls": [
                {
                    "name": "log_turn",
                    "arguments": {
                        "learner_utterance": "El parque es cerca de mi casa.",
                        "errors": [
                            {
                                "type": "ser_estar",
                                "produced": "es cerca",
                                "target": "está cerca",
                            }
                        ],
                        "fluency_signal": "moderate",
                        "L1_used": False,
                    },
                }
            ],
        },
        "metadata": {
            "cefr_band": "A1",
            "learner_production_level": 0.15,
            "errors_present": ["ser_estar"],
            "expected_recast": "está cerca",
            "L1_used": False,
            "fluency_signal": "moderate",
            "difficulty": "straightforward",
            "tags": [],
        },
        "negative_examples": [
            {
                "label": "explicit_correction",
                "response": "No se dice 'es cerca', se dice 'está cerca'.",
                "why_bad": "explicit correction",
            }
        ],
    }


def _make(mutator=None) -> Fixture:
    data = _base_fixture_dict()
    if mutator:
        mutator(data)
    result = parse_fixture(data)
    assert isinstance(result, Fixture)
    return result


class TestBaselineFixturePasses:
    def test_baseline_validates_clean(self):
        fixture = _make()
        assert universal_checks(fixture) == []

    def test_baseline_passes_full_validate_one(self):
        fixture = _make()
        result = validate_one(fixture, "single_error_recast")
        assert result.ok, f"unexpected: {result.errors}"


class TestForbiddenKeys:
    def test_errors_observed_rejected(self):
        def m(data):
            args = data["expected"]["tool_calls"][0]["arguments"]
            args["errors_observed"] = args.pop("errors")

        fixture = _make(m)
        errs = universal_checks(fixture)
        assert any("errors_observed" in e for e in errs)

    def test_errors_detected_rejected(self):
        def m(data):
            args = data["expected"]["tool_calls"][0]["arguments"]
            args["errors_detected"] = args.pop("errors")

        fixture = _make(m)
        errs = universal_checks(fixture)
        assert any("errors_detected" in e for e in errs)


class TestCanonicalTypeRequirement:
    def test_non_canonical_type_rejected(self):
        def m(data):
            data["expected"]["tool_calls"][0]["arguments"]["errors"][0]["type"] = (
                "subjunctive_after_emotion_verb"
            )

        fixture = _make(m)
        errs = universal_checks(fixture)
        assert any("not a canonical type" in e for e in errs)

    def test_each_canonical_type_accepted(self):
        from scripts.fixtures.prompts import ALL_ERROR_TYPES

        for canonical in ALL_ERROR_TYPES:

            def m(data, c=canonical):
                # Set errors_present so the type validation block runs.
                data["metadata"]["errors_present"] = [c]
                data["expected"]["tool_calls"][0]["arguments"]["errors"][0]["type"] = c

            fixture = _make(m)
            errs = [e for e in universal_checks(fixture) if "canonical type" in e]
            assert not errs, f"{canonical} rejected: {errs}"


class TestProducedTargetRequired:
    def test_empty_produced_rejected(self):
        def m(data):
            data["expected"]["tool_calls"][0]["arguments"]["errors"][0]["produced"] = ""

        fixture = _make(m)
        errs = universal_checks(fixture)
        assert any("produced is empty" in e for e in errs)

    def test_empty_target_rejected(self):
        def m(data):
            data["expected"]["tool_calls"][0]["arguments"]["errors"][0]["target"] = ""

        fixture = _make(m)
        errs = universal_checks(fixture)
        assert any("target is empty" in e for e in errs)

    def test_no_check_when_no_errors_present(self):
        # If metadata.errors_present is empty, the produced/target check should
        # not fire — fixtures without errors are legitimate.
        def m(data):
            data["metadata"]["errors_present"] = []
            data["metadata"]["expected_recast"] = None
            data["expected"]["recast_form"] = None
            data["expected"]["response_text"] = "Genial. ¿Qué planes tienes?"
            data["expected"]["tool_calls"][0]["arguments"]["errors"] = []

        fixture = _make(m)
        errs = universal_checks(fixture)
        # Should pass cleanly — no error-related complaints.
        assert not any("produced" in e for e in errs)
        assert not any("target" in e for e in errs)
        assert not any("canonical type" in e for e in errs)


class TestErrorEntryShape:
    def test_string_error_entry_rejected(self):
        # Some legacy fixtures store errors as bare strings — not dicts.
        def m(data):
            data["expected"]["tool_calls"][0]["arguments"]["errors"] = ["ser_estar"]

        fixture = _make(m)
        errs = universal_checks(fixture)
        assert any("not an object" in e for e in errs)


class TestErrorFormLeak:
    def test_produced_form_in_response_rejected(self):
        # The recast must NOT echo the wrong form the learner used.
        def m(data):
            data["expected"]["response_text"] = (
                "El parque es cerca de tu casa, claro. ¿Vas mucho?"
            )
            # produced='es cerca' now appears in response

        fixture = _make(m)
        errs = universal_checks(fixture)
        assert any("appears in response_text" in e for e in errs)

    def test_substring_within_longer_word_not_flagged(self):
        # The legacy substring check would flag produced='es' inside 'está' —
        # but 'es' is a substring of a different lemma, not an echo. Word
        # boundaries should let this pass.
        def m(data):
            args = data["expected"]["tool_calls"][0]["arguments"]
            args["errors"][0]["produced"] = "es"
            args["errors"][0]["target"] = "está"
            data["expected"]["response_text"] = "Ah, está cerca de tu casa. ¿Vas mucho?"

        fixture = _make(m)
        errs = universal_checks(fixture)
        # 'es' should NOT be flagged as leaking just because it's inside 'está'.
        assert not any("appears in response_text" in e for e in errs), errs

    def test_standalone_word_still_flagged(self):
        # The word-boundary fix must NOT regress real echoes — if the wrong
        # form appears as a standalone word, still catch it.
        def m(data):
            args = data["expected"]["tool_calls"][0]["arguments"]
            args["errors"][0]["produced"] = "es"
            args["errors"][0]["target"] = "está"
            data["expected"]["response_text"] = "Sí, es cerca y está bien. ¿Vas mucho?"

        fixture = _make(m)
        errs = universal_checks(fixture)
        assert any("appears in response_text" in e for e in errs)
