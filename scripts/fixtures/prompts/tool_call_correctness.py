"""tool_call_correctness — scaled fixture generation with variance axes.

Primary signal: tool call argument accuracy (the `tool_args_correct` eval
metric). Has-error / clean-turn split is roughly 60/40 — the failing eval
metric is dominated by under-populating `errors` on actual error turns, so
weight the deck toward the failing case.
"""

from __future__ import annotations

import random

from eval.fixtures.schema import CEFRBand

from . import ERROR_TYPES_BY_BAND
from ._variance import pick_surface_form, render_axes_block, sample_axes

DOMAINS = [
    "food_and_cooking",
    "family_and_friends",
    "work_and_study",
    "travel_and_transport",
    "weekend_plans",
    "hobbies_and_music",
    "health_and_sports",
    "city_life",
    "weather_and_seasons",
    "shopping",
]


def build_user_prompts(n: int, band: CEFRBand) -> list[str]:
    errors = ERROR_TYPES_BY_BAND[band]
    prompts: list[str] = []
    for i in range(n):
        rng = random.Random(f"{band}:tool:{i}")
        # 60/40 split toward error turns — under-populated `errors` is the
        # dominant failure mode in the eval, so weight training data accordingly.
        has_error = rng.random() < 0.6
        domain = rng.choice(DOMAINS)
        difficulty, fluency, turn_count = sample_axes(band, i, salt="tool")
        error = errors[i % len(errors)] if has_error else None
        surface = pick_surface_form(error, band, i) if error is not None else ""

        if has_error:
            error_block = (
                f"Final learner turn: contains exactly ONE error of type **{error}**.\n"
                f"Specific realisation to target: {surface}\n"
            )
            errors_requirement = (
                f"- `errors` MUST contain one entry with type=`{error}`, "
                "non-empty `produced` (verbatim wrong form from the utterance), "
                "and non-empty `target` (corrected form)"
            )
        else:
            error_block = "Final learner turn: is CLEAN (no errors).\n"
            errors_requirement = (
                "- `errors` MUST be an empty list `[]` (no errors to log)"
            )

        prompts.append(
            f"""Generate ONE `tool_call_correctness` fixture for CEFR band {band}.

{error_block}Theme domain: **{domain}**

{render_axes_block(difficulty, fluency, turn_count)}

The primary signal under test is tool call accuracy. The conversational
response quality is secondary — an otherwise great response with inaccurate
`log_turn` arguments fails this category.

`log_turn.arguments` accuracy requirements:
- `learner_utterance` is a byte-exact match of the last user turn
- Use the canonical key `errors` (NOT `errors_observed` / `errors_detected`)
{errors_requirement}
- `fluency_signal` matches the variance constraint above
- `L1_used` accurately reflects whether English appeared

Required negative examples (exactly three):
- `wrong_utterance_logged` — learner_utterance doesn't match
- `invented_errors` — logs errors that weren't there (or wrong type)
- `missing_log_turn` — no log_turn tool call at all"""
        )
    return prompts
