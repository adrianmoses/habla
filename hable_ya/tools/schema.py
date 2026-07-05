"""Tool schemas advertised to the LLM.

Runtime pipeline defines one tool today: ``log_turn``. Its argument shape is
the same canonical payload used throughout fixture eval, SFT training, and
the runtime observation sink (see ``hable_ya.pipeline.prompts.render`` for
the shared constants). Spec 049 adds the ``cefr_band`` parameter.

Two representations of the same tool live here:

- ``LOG_TURN_TOOL`` / ``HABLE_YA_TOOLS`` — the OpenAI-style dict form, kept for
  offline fixture eval (``eval/scoring/turn.py``) and documentation.
- ``LOG_TURN_FUNCTION_SCHEMA`` / ``HABLE_YA_TOOLS_SCHEMA`` — Pipecat's
  ``FunctionSchema`` / ``ToolsSchema`` form, which is what actually gets
  registered on the runtime ``LLMContext`` so Claude calls the tool natively
  (spec 001). A raw OpenAI dict passed to ``LLMContext`` would be treated as a
  ``SHIM`` custom tool and dropped by the Anthropic adapter, so the runtime
  must use the ``FunctionSchema`` form.
"""

from __future__ import annotations

from typing import Any

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from hable_ya.learner.bands import ALL_BANDS as VALID_CEFR_BANDS
from hable_ya.pipeline.prompts.render import BAND_RUBRIC_GLOSS


def _build_cefr_band_description() -> str:
    """Render the per-band gloss into a single self-documenting description."""
    parts = [
        "Your CEFR-level read of the learner's LAST utterance, based on its "
        "production characteristics (sentence complexity, tense usage, "
        "vocabulary range, discourse) — not on the topic of the conversation.",
    ]
    for band in VALID_CEFR_BANDS:
        parts.append(f"{band}: {BAND_RUBRIC_GLOSS[band]}.")
    return " ".join(parts)


LOG_TURN_NAME = "log_turn"
LOG_TURN_DESCRIPTION = (
    "Record a structured observation of the learner's last turn. Call "
    "exactly once after every reply."
)

# Single source of truth for the argument shape. Referenced by both the dict
# form (LOG_TURN_TOOL) and the Pipecat FunctionSchema form below so the two
# can't drift.
LOG_TURN_PROPERTIES: dict[str, Any] = {
    "learner_utterance": {
        "type": "string",
        "description": "The learner's last message copied verbatim.",
    },
    "errors": {
        "type": "array",
        "description": (
            "Errors observed in the learner's last turn. Empty list if none."
        ),
        "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "produced": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["type", "produced", "target"],
            "additionalProperties": False,
        },
    },
    "fluency_signal": {
        "type": "string",
        "enum": ["weak", "moderate", "strong"],
        "description": "Overall fluency read of the learner's last turn.",
    },
    "L1_used": {
        "type": "boolean",
        "description": (
            "True if the learner's last turn contained any English word."
        ),
    },
    "cefr_band": {
        "type": "string",
        "enum": list(VALID_CEFR_BANDS),
        "description": _build_cefr_band_description(),
    },
}

LOG_TURN_REQUIRED: list[str] = [
    "learner_utterance",
    "errors",
    "fluency_signal",
    "L1_used",
    "cefr_band",
]


LOG_TURN_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": LOG_TURN_NAME,
        "description": LOG_TURN_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": LOG_TURN_PROPERTIES,
            "required": LOG_TURN_REQUIRED,
            "additionalProperties": False,
        },
    },
}

HABLE_YA_TOOLS: list[dict[str, object]] = [LOG_TURN_TOOL]


# Pipecat-native form: what the runtime registers on the LLMContext so Claude
# emits `log_turn` as a native tool call (spec 001). The Anthropic adapter
# converts a FunctionSchema into `{name, description, input_schema}`.
LOG_TURN_FUNCTION_SCHEMA = FunctionSchema(
    name=LOG_TURN_NAME,
    description=LOG_TURN_DESCRIPTION,
    properties=LOG_TURN_PROPERTIES,
    required=LOG_TURN_REQUIRED,
)

HABLE_YA_TOOLS_SCHEMA = ToolsSchema(standard_tools=[LOG_TURN_FUNCTION_SCHEMA])
