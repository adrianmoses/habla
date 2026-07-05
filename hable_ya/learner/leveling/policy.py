"""Pure functions for placement and auto-leveling decisions.

Two entry points:

* :func:`place_band` — modal band over the diagnostic session's turns.
  Used once at end of an uncalibrated session to seed
  ``learner_profile.band``.
* :func:`evaluate_leveling` — rolling-mean band-as-numeric over the last
  N sessions, with asymmetric hysteresis (K=3 promote, K=4 demote) and a
  demotion-only crossing-margin requirement. Used at end of every
  calibrated session to decide promote / demote / stable.

Both functions are deterministic: identical inputs yield identical
outputs. The async wrapper in :mod:`hable_ya.learner.leveling.service`
adds the asyncpg reads/writes around them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Any, Literal

from eval.fixtures.schema import CEFRBand
from hable_ya.learner.bands import (
    ALL_BANDS,
    BAND_BUCKETS,
    BAND_MIDPOINT,
    band_index,
    bucket_band,
)

# Re-exports for callers that already used these names from this module.
__all__ = [
    "ALL_BANDS",
    "BAND_BUCKETS",
    "BAND_MIDPOINT",
    "BAND_TO_FLOAT",
    "LevelingDecision",
    "PlacementDecision",
    "band_index",
    "bucket_band",
    "evaluate_leveling",
    "place_band",
]
BAND_TO_FLOAT = BAND_MIDPOINT


@dataclass(frozen=True, slots=True)
class PlacementDecision:
    band: CEFRBand
    signals: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LevelingDecision:
    new_band: CEFRBand
    reason: Literal["auto_promote", "auto_demote", "stable"]
    signals: dict[str, Any]


def place_band(
    turn_bands: Sequence[CEFRBand | None],
    *,
    floor_band: CEFRBand = "A2",
    min_valid_turns: int = 3,
) -> PlacementDecision | None:
    """Modal band over valid (non-None) turn observations.

    Returns ``None`` if fewer than ``min_valid_turns`` turns carried a
    valid band — caller is expected to abstain (the learner stays
    uncalibrated, re-enters the diagnostic on the next session).

    Tie-break: when two bands tie on count, prefer the higher band — gives
    the learner the benefit of the doubt; auto-leveling will demote later
    if the placement was generous.

    Floor: the returned band is at least ``floor_band``. The model
    sometimes overweights filler-pause turns toward A1; the floor stops
    cold-start from anchoring the learner below A2 unless every turn
    really is A1.
    """
    valid = [b for b in turn_bands if b is not None]
    if len(valid) < min_valid_turns:
        return None
    counts = Counter(valid)
    # ``max`` with a tuple key: count first, then band-as-numeric for the
    # higher-band tie-break.
    modal: CEFRBand = max(
        counts.items(),
        key=lambda kv: (kv[1], BAND_TO_FLOAT[kv[0]]),
    )[0]
    placed: CEFRBand
    if BAND_TO_FLOAT[modal] >= BAND_TO_FLOAT[floor_band]:
        placed = modal
    else:
        placed = floor_band
    return PlacementDecision(
        band=placed,
        signals={
            "modal_band": modal,
            "counts": {b: counts[b] for b in ALL_BANDS if counts[b]},
            "valid_turns": len(valid),
            "total_turns": len(turn_bands),
            "floor_applied": placed != modal,
        },
    )


def evaluate_leveling(
    *,
    current_band: CEFRBand,
    recent_turn_bands: Sequence[CEFRBand],
    stable_sessions: int,
    promote_consecutive: int = 3,
    demote_consecutive: int = 4,
) -> LevelingDecision:
    """Asymmetric-hysteresis decision over the recent rolling window.

    ``recent_turn_bands`` is the per-turn band stream from the last N
    sessions, with ``None`` already filtered out by the caller. Empty
    input → ``stable`` (no signal).

    ``stable_sessions`` is the count of consecutive prior sessions whose
    target band matched the **current** flow direction (promote toward
    target, or demote toward target). The caller increments this on
    each ``stable`` decision toward the same target and resets it on a
    flip or on a target switch — see :class:`LevelingService` for the
    accounting.

    Decision tree:

    * Empty window → ``stable`` (``no_data``).
    * Target == current band → ``stable``; caller increments
      ``stable_sessions`` toward the current band.
    * Target above current → promote path. ``stable_sessions + 1`` reaches
      ``promote_consecutive`` → ``auto_promote``; otherwise ``stable``
      with ``toward=target``.
    * Target below current → demote path with two extra guards:
      (a) the rolling mean must cross at least one full band-width into
      the lower band — i.e. mean must be ≤ the lower band's bucket
      center, not just below the boundary. A borderline session
      doesn't start the demotion clock at all. (b) Once those guards
      pass, ``stable_sessions + 1`` reaches ``demote_consecutive`` →
      ``auto_demote``.

    Floor (A1) and ceiling (C1) are no-ops by construction: bucket_band
    can never return a band lower than A1 or higher than C1.
    """
    if not recent_turn_bands:
        return LevelingDecision(
            new_band=current_band,
            reason="stable",
            signals={"reason": "no_data"},
        )

    mean_score = fmean(BAND_TO_FLOAT[b] for b in recent_turn_bands)
    target = bucket_band(mean_score)

    base_signals: dict[str, Any] = {
        "mean_band_score": round(mean_score, 4),
        "target_band": target,
        "current_band": current_band,
        "valid_turns": len(recent_turn_bands),
        "stable_sessions_before": stable_sessions,
    }

    if target == current_band:
        return LevelingDecision(
            new_band=current_band,
            reason="stable",
            signals={**base_signals, "toward": current_band},
        )

    target_idx = band_index(target)
    current_idx = band_index(current_band)

    if target_idx > current_idx:
        # Promote path. No crossing-margin gate — promotion is fast.
        if stable_sessions + 1 >= promote_consecutive:
            return LevelingDecision(
                new_band=target,
                reason="auto_promote",
                signals={**base_signals, "toward": target},
            )
        return LevelingDecision(
            new_band=current_band,
            reason="stable",
            signals={**base_signals, "toward": target},
        )

    # Demote path: target below current. Require the mean to cross at
    # least one full band-width into the lower band — i.e. mean ≤ lower
    # band's bucket center, not just below the boundary. Borderline
    # sessions never start the demotion clock.
    target_center = BAND_TO_FLOAT[target]
    if mean_score > target_center:
        return LevelingDecision(
            new_band=current_band,
            reason="stable",
            signals={**base_signals, "toward": "borderline"},
        )

    if stable_sessions + 1 >= demote_consecutive:
        return LevelingDecision(
            new_band=target,
            reason="auto_demote",
            signals={**base_signals, "toward": target},
        )
    return LevelingDecision(
        new_band=current_band,
        reason="stable",
        signals={**base_signals, "toward": target},
    )
