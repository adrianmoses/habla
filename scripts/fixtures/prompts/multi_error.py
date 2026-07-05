"""multi_error — scaled fixture generation with variance axes."""

from __future__ import annotations

import random

from eval.fixtures.schema import CEFRBand

from . import ERROR_TYPES_BY_BAND
from ._variance import sample_axes

PRIORITY_RULE = """
Priority rule (must be applied consistently):
1. Errors that impede comprehension (highest)
2. High-frequency grammar (ser/estar, gender agreement, preterite)
3. Low-frequency grammar
4. Vocabulary gaps
5. Register mismatches (lowest)
"""

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
    allowed = ERROR_TYPES_BY_BAND[band]
    allowed_str = ", ".join(f"`{e}`" for e in allowed)
    prompts: list[str] = []
    for i in range(n):
        # multi_error category requires metadata.difficulty == "multi_error"
        # (enforced by validate_fixtures._check_multi_error), so we only sample
        # the fluency and turn-count axes here — difficulty is fixed.
        _, fluency, turn_count = sample_axes(band, i, salt="multi")
        # Pick 2-3 distinct error types per fixture, seeded for reproducibility.
        rng = random.Random(f"{band}:multi_combo:{i}")
        combo_size = rng.choice([2, 3]) if len(allowed) >= 3 else 2
        combo = rng.sample(allowed, k=min(combo_size, len(allowed)))
        priority = combo[0]
        ignored = combo[1:]
        domain = DOMAINS[i % len(DOMAINS)]

        prompts.append(
            f"""Generate ONE `multi_error` fixture for CEFR band {band}.

Theme domain: **{domain}**
Error combination (use exactly these in the learner utterance):
- Priority error to recast: **{priority}**
- Ignored errors: {", ".join(f"**{e}**" for e in ignored)}

Variance constraints (use these EXACT values):
- Fluency signal: **{fluency}** — set `metadata.fluency_signal` and
  `log_turn.arguments.fluency_signal` to this. Phrase the learner utterance
  accordingly (weak = hesitations, fragments; moderate = complete sentences
  with errors; strong = fluent and extended).
- Prior assistant turns: **{turn_count}** assistant turn(s) before the final
  learner utterance.
- `metadata.difficulty` MUST be the literal string `"multi_error"` — do NOT
  use `straightforward` or `ambiguous` for this category.

The learner utterance must contain ALL {len(combo)} of the listed errors,
naturally integrated. The agent recasts ONLY the priority error and lets the
others pass, but the `log_turn` tool call records ALL errors observed.

{PRIORITY_RULE}

## Allowed error types for {band}

Use ONLY these exact strings for `errors_present`, log_turn `errors[].type`,
`priority_error`, and `ignored_errors`: {allowed_str}

Required fields in `expected`:
- `priority_error`: `{priority}`
- `ignored_errors`: {ignored}

`log_turn` tool call requirements:
- Use the canonical key `errors` (NOT `errors_observed` / `errors_detected`).
- Each entry: non-empty `type`, `produced` (verbatim wrong form from
  learner_utterance), and `target` (the corrected form). For ignored errors,
  set `target` to the form they SHOULD have used even though you didn't recast.

Metadata:
- `errors_present` lists all {len(combo)} error types
- `fluency_signal` matches the variance constraint above

Required negative examples (exactly three):
- `recasts_wrong_error` — recasts a lower-priority error
- `recasts_all_errors` — tries to fix every error
- `explicit_correction`"""
        )
    return prompts
