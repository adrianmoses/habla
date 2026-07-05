"""cold_start — 20 fixtures (4 per band). Different schema from other categories."""

from __future__ import annotations

from eval.fixtures.schema import CEFRBand

TRAPS = [
    ("consistent_signal", "Clean, unambiguous signal throughout all 4 turns."),
    (
        "starts_hesitant_improves",
        "Learner is hesitant in turns 1–2 then warms up; agent must adjust upward.",
    ),
    (
        "overconfident_errors",
        "Learner attempts complex structures but with systematic errors — don't over-estimate.",
    ),
    (
        "heavy_L1_early",
        "Learner uses English in turns 1–2 then switches to Spanish — reassess.",
    ),
]


def build_user_prompts(n: int, band: CEFRBand) -> list[str]:
    prompts: list[str] = []
    for i in range(n):
        trap_label, trap_desc = TRAPS[i % len(TRAPS)]
        prompts.append(
            f"""Generate ONE `cold_start` fixture (type="cold_start_sequence").

Target true band: **{band}**
Calibration trap: **{trap_label}** — {trap_desc}

Schema differences from other categories:
- No `expected` block, no `conversation`, no `negative_examples`
- Instead: `learner_turns` (exactly 4), `true_level`, `true_band`,
  `expected_profile_update`
- Each learner turn carries `signals` (L1_used, fluency, band_indicators)

`expected_profile_update.production_level` must be a {{min, max}} range that
contains `true_level` ±0.15. `is_calibrated` must be true after turn 4.

Tags should include "cold_start", the trap label, and the band.
No negative examples for this category.

Variation #{i + 1} of {n}."""
        )
    return prompts
