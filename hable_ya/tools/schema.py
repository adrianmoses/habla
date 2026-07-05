"""Tool schemas advertised to the LLM.

Runtime pipeline defines one tool today: ``log_turn``. Its argument shape is
the same canonical payload used throughout fixture eval, SFT training, and
the runtime observation sink (see ``hable_ya.pipeline.prompts.render`` for
the shared constants). Spec 049 adds the ``cefr_band`` parameter as a
prompt-only signal — the fine-tuned Gemma was trained on the prior 4-field
shape, so emission is best-effort and the runtime tolerates missing values.
"""

from __future__ import annotations

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


LOG_TURN_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "log_turn",
        "description": (
            "Record a structured observation of the learner's last turn. Call "
            "exactly once after every reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "learner_utterance": {
                    "type": "string",
                    "description": "The learner's last message copied verbatim.",
                },
                "errors": {
                    "type": "array",
                    "description": (
                        "Errors observed in the learner's last turn. Empty "
                        "list if none."
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
                    "description": ("Overall fluency read of the learner's last turn."),
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
            },
            "required": [
                "learner_utterance",
                "errors",
                "fluency_signal",
                "L1_used",
                "cefr_band",
            ],
            "additionalProperties": False,
        },
    },
}

HABLE_YA_TOOLS: list[dict[str, object]] = [LOG_TURN_TOOL]
