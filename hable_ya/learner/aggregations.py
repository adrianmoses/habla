"""Pure aggregation helpers for the learner profile snapshot.

Single source of truth for the rolling-mean and top-N rules. Both
`LearnerProfileRepo.get` (production path, populates from SQL) and the
agent-eval `ProfileAccumulator` (eval path, populates from log_turn parses)
call `compute_snapshot` so eval and runtime cannot drift silently.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from eval.fixtures.schema import CEFRBand, FluencySignal

_FLUENCY_TO_FLOAT: dict[FluencySignal, float] = {
    "weak": 0.3,
    "moderate": 0.6,
    "strong": 0.9,
}

_NEUTRAL_L1 = 0.5
_NEUTRAL_FLUENCY = 0.5


@dataclass(slots=True, frozen=True)
class LearnerProfileSnapshot:
    band: CEFRBand
    sessions_completed: int
    l1_reliance: float = _NEUTRAL_L1
    speech_fluency: float = _NEUTRAL_FLUENCY
    error_patterns: list[str] = field(default_factory=list)
    vocab_strengths: list[str] = field(default_factory=list)


def compute_snapshot(
    *,
    band: CEFRBand,
    sessions_completed: int,
    l1_used_flags: Sequence[bool],
    fluency_signals: Sequence[FluencySignal],
    error_counter: Mapping[str, int],
    error_last_seen: Mapping[str, datetime],
    vocab_last_seen: Mapping[str, datetime],
    top_errors: int,
    top_vocab: int,
) -> LearnerProfileSnapshot:
    """Compose a snapshot from pre-tallied inputs.

    `l1_used_flags` and `fluency_signals` are the rolling window already
    trimmed by the caller (size <= window_turns). Empty sequences yield the
    neutral defaults.

    `error_counter` and `error_last_seen` cover the same set of keys; top-N
    selection uses count DESC with last_seen DESC as tiebreaker, mirroring
    the SQL `ORDER BY count DESC, last_seen_at DESC` in the production repo.

    `vocab_last_seen` keys are lemmas; selection is last_seen DESC only.
    """
    if l1_used_flags:
        l1_reliance = sum(1.0 for f in l1_used_flags if f) / len(l1_used_flags)
    else:
        l1_reliance = _NEUTRAL_L1

    if fluency_signals:
        speech_fluency = sum(
            _FLUENCY_TO_FLOAT[s] for s in fluency_signals
        ) / len(fluency_signals)
    else:
        speech_fluency = _NEUTRAL_FLUENCY

    error_items = list(error_counter.items())
    error_items.sort(
        key=lambda item: error_last_seen[item[0]],
        reverse=True,
    )
    error_items.sort(key=lambda item: item[1], reverse=True)
    error_patterns = [cat for cat, _ in error_items[:top_errors]]

    vocab_items = sorted(
        vocab_last_seen.items(), key=lambda item: item[1], reverse=True
    )
    vocab_strengths = [lemma for lemma, _ in vocab_items[:top_vocab]]

    return LearnerProfileSnapshot(
        band=band,
        sessions_completed=sessions_completed,
        l1_reliance=l1_reliance,
        speech_fluency=speech_fluency,
        error_patterns=error_patterns,
        vocab_strengths=vocab_strengths,
    )
