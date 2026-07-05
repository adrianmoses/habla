"""Spec 049 — placement + auto-leveling, from model-emitted ``cefr_band``.

Two layers:

* :mod:`hable_ya.learner.leveling.policy` — pure functions
  (:func:`place_band`, :func:`evaluate_leveling`) over plain band sequences.
  No DB, no async. Same shape ``compute_snapshot`` exposes for spec 029, so
  ``replay_placement.py`` and unit tests share the decision surface with
  the runtime.
* :mod:`hable_ya.learner.leveling.service` —
  :class:`LevelingService` wraps the pure functions in asyncpg I/O. Reads
  the recent ``turns`` rows, makes the decision, writes
  ``learner_profile`` + ``band_history`` in one transaction.
"""

from __future__ import annotations

from hable_ya.learner.leveling.policy import (
    BAND_BUCKETS,
    BAND_TO_FLOAT,
    LevelingDecision,
    PlacementDecision,
    bucket_band,
    evaluate_leveling,
    place_band,
)
from hable_ya.learner.leveling.service import LevelingService

__all__ = [
    "BAND_BUCKETS",
    "BAND_TO_FLOAT",
    "LevelingDecision",
    "LevelingService",
    "PlacementDecision",
    "bucket_band",
    "evaluate_leveling",
    "place_band",
]
