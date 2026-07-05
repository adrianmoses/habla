"""Prompt templates for fixture generation."""

from __future__ import annotations

from collections.abc import Callable

from eval.fixtures.schema import CEFRBand

# Canonical error type vocabulary. All prompts and validation must use these
# exact strings for errors_present, errors_observed, and priority_error fields.
ERROR_TYPES_BY_BAND: dict[CEFRBand, list[str]] = {
    "A1": ["gender_agreement", "missing_article", "verb_conjugation", "ser_estar"],
    "A2": ["gender_agreement", "ser_estar", "preterite_imperfect", "verb_conjugation"],
    "B1": ["ser_estar", "preterite_imperfect", "subjunctive_avoidance", "por_para"],
    "B2": ["subjunctive", "por_para", "register_slip", "idiomatic_error"],
    "C1": ["subjunctive", "register_slip", "idiomatic_error"],
}

ALL_ERROR_TYPES = sorted({t for types in ERROR_TYPES_BY_BAND.values() for t in types})

from . import (  # noqa: E402  (submodules import ERROR_TYPES_BY_BAND from this file)
    cold_start,
    error_pattern_threshold,
    l1_handling,
    mimicry_cycle,
    multi_error,
    register_boundary,
    single_error_recast,
    tool_call_correctness,
)

BuildPrompts = Callable[[int, CEFRBand], list[str]]

CATEGORIES: dict[str, BuildPrompts] = {
    "single_error_recast": single_error_recast.build_user_prompts,
    "multi_error": multi_error.build_user_prompts,
    "l1_handling": l1_handling.build_user_prompts,
    "mimicry_cycle": mimicry_cycle.build_user_prompts,
    "cold_start": cold_start.build_user_prompts,
    "register_boundary": register_boundary.build_user_prompts,
    "tool_call_correctness": tool_call_correctness.build_user_prompts,
    "error_pattern_threshold": error_pattern_threshold.build_user_prompts,
}

# Targets are bumped only for the three categories that exercise the two
# remaining-weak eval metrics (recast_present, tool_args_correct). The other
# categories stay at their original small counts because their metrics already
# pass under prompt engineering — no fine-tune signal to scale toward.
#
# Failure-weighted distribution: A1 had 25/83 tool_args failures, C1 had 24/80
# recast_present failures — both bands get extra weight in single_error_recast.
TARGET_COUNTS: dict[str, dict[CEFRBand, int]] = {
    # Fine-tune targets — scaled.
    "single_error_recast": {"A1": 150, "A2": 120, "B1": 100, "B2": 100, "C1": 150},
    "multi_error": {"A1": 60, "A2": 60, "B1": 60, "B2": 60, "C1": 60},
    "tool_call_correctness": {"A1": 40, "A2": 30, "B1": 30, "B2": 30, "C1": 30},
    # Prompt-engineering territory — left at original small counts (current
    # eval metrics already pass for these). Scale only if a regression appears.
    "l1_handling": {"A1": 5, "A2": 5, "B1": 5, "B2": 5, "C1": 5},
    "mimicry_cycle": {"A1": 15},
    "cold_start": {"A1": 4, "A2": 4, "B1": 4, "B2": 4, "C1": 4},
    "register_boundary": {"A1": 4, "A2": 4, "B1": 4, "B2": 4, "C1": 4},
    "error_pattern_threshold": {"A1": 4, "A2": 4, "B1": 4, "B2": 4, "C1": 4},
}
