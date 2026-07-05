"""single_error_recast — scaled fixture generation with variance axes."""

from __future__ import annotations

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
        # Distribute errors and domains evenly; sample variance axes per fixture
        # so 100 ser_estar fixtures don't all end up with identical scaffolding.
        error = errors[i % len(errors)]
        domain = DOMAINS[i % len(DOMAINS)]
        difficulty, fluency, turn_count = sample_axes(band, i)
        surface = pick_surface_form(error, band, i)

        surface_line = f"Specific realisation to target: {surface}\n" if surface else ""

        prompts.append(
            f"""Generate ONE `single_error_recast` fixture for CEFR band {band}.

Error type to showcase: **{error}**
Theme domain: **{domain}**
{surface_line}
{render_axes_block(difficulty, fluency, turn_count)}

The learner utterance must contain exactly one natural-sounding instance of
this error — nothing else wrong. The agent response must:
- Recast the error implicitly (correct form appears, error form absent)
- Be in the register appropriate for {band}
- Be 1–3 sentences with exactly one question
- Include a `log_turn` tool call with the canonical `errors` key, each entry
  having non-empty `type` (=`{error}`), `produced` (the wrong form verbatim
  from the learner_utterance), and `target` (the corrected form woven into
  your response)

Provide these three negative examples (required labels, exactly three):
- `explicit_correction` — names the error directly
- `no_recast` — correct form never appears
- `too_long` — 4+ sentences, agent dominates"""
        )
    return prompts
