"""Persona schema and loader for the agent-eval simulator.

A persona authors a simulated learner: their CEFR band, the scenario domain
to drive, the grammatical errors they'll repeat, how often they fall back
to English, and how fluent their Spanish sounds. The orchestrator turns
the persona into the system prompt for the Opus learner-side call and
into the band/theme inputs for the agent-side call.

Validation fails fast on:
- `scenario_domain` not present in `THEMES_BY_LEVEL[persona.cefr_band]`
- `error_patterns` entries outside `ALLOWED_ERROR_PATTERNS`

The allowed-error-pattern list is hand-curated from the categories the
hand-authored fixtures use most often. Add to it deliberately.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eval.fixtures.schema import CEFRBand, FluencySignal
from hable_ya.learner.themes import THEMES_BY_LEVEL

# Curated from fixture inventory; covers the categories the fine-tune
# targets in `single_error_recast`, `multi_error`, and `tool_call_correctness`.
# Personas may name 1-2 of these; the simulator's job is to reproduce them.
ALLOWED_ERROR_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "ser_estar",
        "gender_agreement",
        "preterite_imperfect",
        "por_para",
        "verb_conjugation",
        "register_slip",
        "idiomatic_error",
        "subjunctive_avoidance",
        "subjunctive",
        "missing_article",
        "stem_changing_verbs",
        "anglicisms",
    }
)


class Persona(BaseModel):
    """Authored simulator profile."""

    model_config = ConfigDict(extra="forbid")

    id: str
    cefr_band: CEFRBand
    scenario_domain: str
    error_patterns: list[str] = Field(min_length=1)
    L1_reliance: float = Field(ge=0.0, le=1.0)
    fluency_signal: FluencySignal
    turn_budget: int = Field(default=12, ge=2, le=40)
    opening_utterance: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_scenario_in_band(self) -> Persona:
        domains = {t.domain for t in THEMES_BY_LEVEL[self.cefr_band]}
        if self.scenario_domain not in domains:
            raise ValueError(
                f"persona {self.id!r}: scenario_domain "
                f"{self.scenario_domain!r} is not a registered theme for band "
                f"{self.cefr_band} (allowed: {sorted(domains)})"
            )
        return self

    @model_validator(mode="after")
    def _check_error_patterns_allowed(self) -> Persona:
        unknown = [e for e in self.error_patterns if e not in ALLOWED_ERROR_PATTERNS]
        if unknown:
            raise ValueError(
                f"persona {self.id!r}: unknown error_patterns {unknown}; "
                f"add them to ALLOWED_ERROR_PATTERNS deliberately if real"
            )
        return self


def load_personas(path: Path) -> list[Persona]:
    """Load every `*.json` under `path` (non-recursive) as a Persona.

    Sorted by `id` for stable iteration. Raises on the first invalid file
    so authoring errors surface immediately.
    """
    personas: list[Persona] = []
    for json_path in sorted(path.glob("*.json")):
        with json_path.open() as f:
            raw = json.load(f)
        personas.append(Persona.model_validate(raw))
    return personas
