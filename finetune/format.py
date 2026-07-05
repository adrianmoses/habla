"""Convert eval fixtures to SFT training format.

Produces JSONL-compatible dicts matching the format in README.md. The per-band
system-prompt renderer and log_turn normalization logic live in
``hable_ya.pipeline.prompts.render`` so the runtime and training paths share one
source of truth.
"""

from __future__ import annotations

import json
from typing import Any

from eval.fixtures.schema import CATEGORY_FILES, Fixture
from hable_ya.pipeline.prompts.render import (
    CANONICAL_KEYS,
    FORBIDDEN_CORRECTION_PHRASES,
    band_from_production_level,
    normalize_error_item,
    normalize_log_turn_args,
    render_system_prompt,
)

__all__ = [
    "CANONICAL_KEYS",
    "FORBIDDEN_CORRECTION_PHRASES",
    "band_from_production_level",
    "fixture_to_sft",
    "normalize_error_item",
    "normalize_log_turn_args",
    "render_system_prompt",
]


def _render_tool_call(name: str, args: dict[str, Any]) -> str:
    """Render a tool call as ``name({...json...})``.

    The base Gemma model has strong priors for this function-call style and
    consistently produces it post-fine-tune; matching that here means the
    training signal reinforces what the model wants to do anyway. The eval
    parser at ``eval/scoring/turn.py`` accepts both this and the legacy
    ``[TOOL_CALL: name]{...}`` form for backward compatibility.
    """
    ordered = {k: args[k] for k in CANONICAL_KEYS if k in args}
    for k, v in args.items():
        if k not in ordered:
            ordered[k] = v
    return f"\n\n{name}({json.dumps(ordered, ensure_ascii=False)})"


def _canonical_log_turn(fixture: Fixture) -> dict[str, Any]:
    """Build the canonical log_turn args from the fixture, preferring its own tool call."""
    for tc in fixture.expected.tool_calls:
        if tc.name == "log_turn":
            return normalize_log_turn_args(fixture, tc.arguments)
    return normalize_log_turn_args(fixture, {})


def _build_assistant_content(fixture: Fixture) -> str:
    """Assemble the target assistant turn: response text + a canonical log_turn call.

    ``log_error`` and other auxiliary tool calls are intentionally dropped so
    the fine-tune target is a single consistent shape.
    """
    args = _canonical_log_turn(fixture)
    return fixture.expected.response_text + _render_tool_call("log_turn", args)


def _extract_category(fixture_id: str) -> str:
    """Derive category from fixture id prefix."""
    for cat in sorted(CATEGORY_FILES, key=len, reverse=True):
        if fixture_id.startswith(cat):
            return cat
    return "unknown"


def fixture_to_sft(fixture: Fixture) -> dict[str, Any]:
    """Convert a standard Fixture to SFT training format.

    Returns a dict with ``messages`` and ``metadata`` keys, ready for
    JSONL serialisation.
    """
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": render_system_prompt(
                fixture.system_params, band=fixture.metadata.cefr_band
            ),
        },
    ]

    for turn in fixture.conversation:
        messages.append({"role": turn.role, "content": turn.content})

    messages.append({"role": "assistant", "content": _build_assistant_content(fixture)})

    metadata: dict[str, Any] = {
        "category": _extract_category(fixture.id),
        "cefr_band": fixture.metadata.cefr_band,
        "error_type": fixture.metadata.errors_present[0]
        if fixture.metadata.errors_present
        else None,
        "difficulty": fixture.metadata.difficulty,
        "weight": 1.0,
    }

    return {"messages": messages, "metadata": metadata}
