"""l1_handling — scaled fixture generation with variance axes."""

from __future__ import annotations

import random

from eval.fixtures.schema import CEFRBand

from ._variance import render_axes_block, sample_axes

SCENARIOS = [
    ("full_english", "Learner responds entirely in English."),
    ("mixed_switch", "Learner starts in Spanish then switches mid-sentence."),
    ("english_word", "Learner uses one English word when vocabulary fails."),
    ("meta_question", "Learner asks 'how do you say X?' in English."),
]

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
    prompts: list[str] = []
    for i in range(n):
        # Seeded scenario + domain pick so distribution stays balanced at scale
        # without locking a fixed cycle.
        rng = random.Random(f"{band}:l1:{i}")
        label, desc = rng.choice(SCENARIOS)
        domain = rng.choice(DOMAINS)
        difficulty, fluency, turn_count = sample_axes(band, i, salt="l1")

        prompts.append(
            f"""Generate ONE `l1_handling` fixture for CEFR band {band}.

L1 scenario: **{label}** — {desc}
Theme domain: **{domain}**

{render_axes_block(difficulty, fluency, turn_count)}

Agent rules:
- Response MUST be 100% Spanish, no English tokens anywhere
- Provide enough context/scaffolding so the learner can infer meaning
  without a translation
- For `meta_question`: answer by embedding the target word naturally in a
  Spanish sentence, not by giving "word = palabra" translations
- `metadata.L1_used` must be true
- `log_turn.arguments.L1_used` must be true
- Tag the fixture with the scenario label

`log_turn` tool call requirements:
- Use the canonical key `errors` (NOT `errors_observed` / `errors_detected`).
- If the learner's L1 use itself is not flagged as a Spanish error, leave
  `errors` as an empty list `[]`. Only populate it for actual Spanish
  errors in any Spanish portion the learner produced.

Required negative examples (exactly three):
- `switches_to_english` — agent uses English
- `ignores_question` — doesn't answer the meta question
- `over_explains` — 4+ sentences explaining"""
        )
    return prompts
