"""HABLE_YA_TOOLS schema tests."""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from pipecat.adapters.services.anthropic_adapter import AnthropicLLMAdapter

from hable_ya.tools.schema import (
    HABLE_YA_TOOLS,
    HABLE_YA_TOOLS_SCHEMA,
    LOG_TURN_PROPERTIES,
    LOG_TURN_REQUIRED,
)


def _log_turn_schema() -> dict[str, object]:
    assert len(HABLE_YA_TOOLS) == 1
    tool = HABLE_YA_TOOLS[0]
    assert isinstance(tool, dict)
    fn = tool["function"]
    assert isinstance(fn, dict)
    params = fn["parameters"]
    assert isinstance(params, dict)
    return params


def test_single_log_turn_tool() -> None:
    assert len(HABLE_YA_TOOLS) == 1
    tool = HABLE_YA_TOOLS[0]
    assert tool["type"] == "function"
    fn = tool["function"]
    assert isinstance(fn, dict)
    assert fn["name"] == "log_turn"
    assert isinstance(fn["description"], str)
    assert fn["description"]


def test_schema_validates_well_formed_args() -> None:
    schema = _log_turn_schema()
    validator = Draft202012Validator(schema)
    payload = {
        "learner_utterance": "Yo es Juan.",
        "errors": [{"type": "ser_estar", "produced": "es", "target": "soy"}],
        "fluency_signal": "moderate",
        "L1_used": False,
        "cefr_band": "A2",
    }
    assert list(validator.iter_errors(payload)) == []


def test_schema_accepts_empty_errors_list() -> None:
    schema = _log_turn_schema()
    validator = Draft202012Validator(schema)
    payload = {
        "learner_utterance": "Hola.",
        "errors": [],
        "fluency_signal": "strong",
        "L1_used": False,
        "cefr_band": "B2",
    }
    assert list(validator.iter_errors(payload)) == []


@pytest.mark.parametrize(
    "bad_payload, reason",
    [
        (
            {
                "errors": [],
                "fluency_signal": "moderate",
                "L1_used": False,
                "cefr_band": "A2",
            },
            "missing learner_utterance",
        ),
        (
            {
                "learner_utterance": "Hola.",
                "errors": "not-a-list",
                "fluency_signal": "moderate",
                "L1_used": False,
                "cefr_band": "A2",
            },
            "errors not a list",
        ),
        (
            {
                "learner_utterance": "Hola.",
                "errors": [],
                "fluency_signal": "ok",
                "L1_used": False,
                "cefr_band": "A2",
            },
            "fluency_signal not in enum",
        ),
        (
            {
                "learner_utterance": "Hola.",
                "errors": [],
                "fluency_signal": "moderate",
                "L1_used": "yes",
                "cefr_band": "A2",
            },
            "L1_used not bool",
        ),
        (
            {
                "learner_utterance": "Hola.",
                "errors": [],
                "fluency_signal": "moderate",
                "L1_used": False,
            },
            "missing cefr_band",
        ),
        (
            {
                "learner_utterance": "Hola.",
                "errors": [],
                "fluency_signal": "moderate",
                "L1_used": False,
                "cefr_band": "intermediate",
            },
            "cefr_band not in enum",
        ),
    ],
)
def test_schema_rejects_malformed_args(
    bad_payload: dict[str, object], reason: str
) -> None:
    schema = _log_turn_schema()
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(bad_payload))
    assert errors, f"expected schema to reject {reason!r}"


def test_native_tools_schema_converts_for_anthropic() -> None:
    """The Pipecat FunctionSchema the runtime registers (spec 001) converts to
    a valid Anthropic tool dict whose shape matches the canonical payload."""
    tools = AnthropicLLMAdapter().from_standard_tools(HABLE_YA_TOOLS_SCHEMA)
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "log_turn"
    assert isinstance(tool["description"], str) and tool["description"]
    input_schema = tool["input_schema"]
    assert set(input_schema["required"]) == set(LOG_TURN_REQUIRED)
    assert set(input_schema["properties"]) == set(LOG_TURN_PROPERTIES)
    assert "cefr_band" in input_schema["properties"]
