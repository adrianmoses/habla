"""error_pattern_threshold — 20 fixtures (4 per band)."""

from __future__ import annotations

from eval.fixtures.schema import CEFRBand

SCENARIOS = [
    (
        "third_occurrence",
        3,
        True,
        "Third time the same error appears across the conversation. Call log_error.",
    ),
    (
        "second_occurrence",
        2,
        False,
        "Only the second time — below threshold. Do NOT call log_error.",
    ),
    (
        "different_contexts",
        3,
        True,
        "Three different sentences with the same underlying error pattern. Call log_error.",
    ),
    (
        "declining_severity",
        3,
        True,
        "Three occurrences but the learner is improving. Call log_error with a trend note in arguments.",
    ),
]


def build_user_prompts(n: int, band: CEFRBand) -> list[str]:
    prompts: list[str] = []
    for i in range(n):
        label, count, call_log_error, desc = SCENARIOS[i % len(SCENARIOS)]
        prompts.append(
            f"""Generate ONE `error_pattern_threshold` fixture for CEFR band {band}.

Scenario: **{label}** ({count} occurrences) — {desc}

Structural requirements:
- `conversation` MUST contain at least 4 prior turns so the pattern
  repetition is visible in context
- The same error pattern appears {count} times across prior learner turns
- `expected.tool_calls` always includes `log_turn`
- `expected.tool_calls` {"includes" if call_log_error else "does NOT include"} `log_error`
- Tag with the scenario label

Required negative examples:
- `calls_log_error_too_early` — fires log_error at 2nd occurrence
- `omits_log_error_at_threshold` — misses it at 3rd occurrence
- `wrong_pattern_identified` — log_error names the wrong pattern

Variation #{i + 1} of {n}."""
        )
    return prompts
