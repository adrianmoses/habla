"""Authoritative Pydantic schema for eval fixtures.

Every fixture file under ``eval/fixtures/*.json`` must parse against one of
the models here. See ``habla_fixture_spec.md`` for the full specification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

CEFRBand = Literal["A1", "A2", "B1", "B2", "C1"]
Difficulty = Literal["straightforward", "ambiguous", "multi_error"]
FluencySignal = Literal["weak", "moderate", "strong"]
Role = Literal["assistant", "user"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LearnerProfile(_Strict):
    production_level: float = Field(ge=0.0, le=1.0)
    L1_reliance: float = Field(ge=0.0, le=1.0)
    speech_fluency: float = Field(ge=0.0, le=1.0)
    is_calibrated: bool
    sessions_completed: int = Field(ge=0)
    vocab_strengths: list[str] = Field(default_factory=list)
    error_patterns: list[str] = Field(default_factory=list)


class Theme(_Strict):
    domain: str
    prompt: str
    target_structures: list[str] = Field(default_factory=list)


class SystemParams(_Strict):
    profile: LearnerProfile
    theme: Theme


class ConversationTurn(_Strict):
    role: Role
    content: str


class ToolCallExpected(_Strict):
    name: str
    arguments: dict[str, Any]


class ExpectedOutput(_Strict):
    response_text: str
    recast_form: str | None = None
    tool_calls: list[ToolCallExpected]
    priority_error: str | None = None
    ignored_errors: list[str] | None = None


class FixtureMetadata(_Strict):
    cefr_band: CEFRBand
    learner_production_level: float = Field(ge=0.0, le=1.0)
    errors_present: list[str] = Field(default_factory=list)
    expected_recast: str | None = None
    L1_used: bool
    fluency_signal: FluencySignal
    difficulty: Difficulty
    tags: list[str] = Field(default_factory=list)


class NegativeExample(_Strict):
    label: str
    response: str
    why_bad: str


class Fixture(_Strict):
    id: str
    type: Literal["standard"] = "standard"
    system_params: SystemParams
    conversation: list[ConversationTurn]
    expected: ExpectedOutput
    metadata: FixtureMetadata
    negative_examples: list[NegativeExample] = Field(min_length=1)


class ColdStartSignals(_Strict):
    L1_used: bool
    fluency: FluencySignal
    band_indicators: list[CEFRBand]


class ColdStartLearnerTurn(_Strict):
    utterance: str
    signals: ColdStartSignals


class _Range(_Strict):
    min: float = Field(ge=0.0, le=1.0)
    max: float = Field(ge=0.0, le=1.0)


class ColdStartExpectedUpdate(_Strict):
    production_level: _Range
    L1_reliance: _Range
    is_calibrated: bool


class ColdStartMetadata(_Strict):
    cefr_band: CEFRBand
    learner_production_level: float = Field(ge=0.0, le=1.0)
    errors_present: list[str] = Field(default_factory=list)
    L1_used: bool
    fluency_signal: FluencySignal
    difficulty: Difficulty
    tags: list[str] = Field(default_factory=list)


class ColdStartFixture(_Strict):
    id: str
    type: Literal["cold_start_sequence"]
    learner_turns: list[ColdStartLearnerTurn] = Field(min_length=4, max_length=4)
    true_level: float = Field(ge=0.0, le=1.0)
    true_band: CEFRBand
    expected_profile_update: ColdStartExpectedUpdate
    metadata: ColdStartMetadata


AnyFixture = Annotated[
    ColdStartFixture | Fixture,
    Field(discriminator="type"),
]

_FIXTURE_ADAPTER: TypeAdapter[ColdStartFixture | Fixture] = TypeAdapter(AnyFixture)
_FIXTURE_LIST_ADAPTER: TypeAdapter[list[ColdStartFixture | Fixture]] = TypeAdapter(
    list[AnyFixture]
)


CATEGORY_FILES = [
    "single_error_recast",
    "multi_error",
    "l1_handling",
    "mimicry_cycle",
    "cold_start",
    "register_boundary",
    "tool_call_correctness",
    "error_pattern_threshold",
]


def parse_fixture(data: dict[str, Any]) -> Fixture | ColdStartFixture:
    """Parse a single fixture dict, dispatching on ``type``."""
    if data.get("type") == "cold_start_sequence":
        return ColdStartFixture.model_validate(data)
    return Fixture.model_validate(data)


def load_fixtures(path: Path) -> list[Fixture | ColdStartFixture]:
    """Load and validate every category JSON under ``path``.

    Raises ``pydantic.ValidationError`` on the first malformed fixture.
    """
    fixtures: list[Fixture | ColdStartFixture] = []
    for name in CATEGORY_FILES:
        file = path / f"{name}.json"
        if not file.exists():
            continue
        raw = json.loads(file.read_text())
        fixtures.extend(_FIXTURE_LIST_ADAPTER.validate_python(raw))
    return fixtures
