"""register_boundary — 20 fixtures (4 per band)."""

from __future__ import annotations

from eval.fixtures.schema import CEFRBand

TRAPS = [
    (
        "high_end_of_band",
        "Learner performs at the top of their stated band. Agent must hold the band register without drifting upward.",
    ),
    (
        "low_end_of_band",
        "Learner struggles at the bottom of their stated band. Agent holds the band register anchored to the profile.",
    ),
    (
        "band_crossing",
        "One utterance is clearly above the band (memorized phrase). Agent does NOT permanently adjust upward for one strong turn.",
    ),
    (
        "regression",
        "Learner drops below expected level mid-topic. Agent temporarily simplifies without abandoning the theme.",
    ),
]


def build_user_prompts(n: int, band: CEFRBand) -> list[str]:
    prompts: list[str] = []
    for i in range(n):
        label, desc = TRAPS[i % len(TRAPS)]
        prompts.append(
            f"""Generate ONE `register_boundary` fixture for CEFR band {band}.

Trap: **{label}** — {desc}

- `metadata.difficulty` must be "ambiguous"
- `metadata.errors_present` may be empty — the signal under test is register,
  not grammar correction
- Tag with the trap label

Required negative examples:
- `drifts_register_up` — agent jumps to a higher band
- `drifts_register_down` — agent over-simplifies
- `over_simplifies` — baby-talk style

Variation #{i + 1} of {n}."""
        )
    return prompts
