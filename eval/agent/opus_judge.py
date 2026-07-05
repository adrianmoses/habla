"""Opus session-outcome judge.

Reads a full session transcript + the persona spec and returns a
`SessionVerdict` with five integer scores (1–5), per-dimension
rationales, and a `stop_reason` label assigned post-hoc. Verdicts are
cached on disk by `sha256(JUDGE_SYSTEM_VERSION + persona.id +
canonical_transcript)`; bumping the version constant invalidates every
prior cache file.

`overall` is computed locally from the five dimensions, not requested
from the LLM, so the schema Opus generates against is exactly the
visible-by-LLM fields. Recompute on cache load happens automatically
because `overall` is a Pydantic computed_field.
"""

from __future__ import annotations

import hashlib
from typing import Final, Literal

import anthropic
from pydantic import BaseModel, Field, computed_field

from eval.agent._cache import (
    JsonDiskCache,
    cached_system_block,
    canonical_transcript,
)
from eval.agent.personas.schema import Persona
from eval.fixtures.schema import ConversationTurn

JUDGE_SYSTEM_VERSION: Final[str] = "2"
DEFAULT_JUDGE_MODEL: Final[str] = "claude-opus-4-7"

JUDGE_SYSTEM = (
    "You are evaluating a Spanish-language tutoring session.\n\n"
    "The transcript below is one full session between a tutoring agent "
    "and a simulated learner. You will score the session on five "
    "dimensions, each 1-5. You will also assign a single `stop_reason` "
    "label describing why the session ended.\n\n"
    "Score 1-5 with these rubrics:\n\n"
    "**pedagogical_flow** - does the conversation progress, or does the "
    "agent stall?\n"
    "- 5: Each turn moves the conversation forward; the agent introduces "
    "relevant follow-ups without forcing topic changes.\n"
    "- 3: Some progress but the agent occasionally repeats itself or asks "
    "loosely related questions.\n"
    "- 1: The agent is stuck in loops, repeats the same elicitation, or "
    "wrenches topics awkwardly.\n\n"
    "**level_consistency** - is the agent's Spanish at the persona's CEFR "
    "band throughout?\n"
    "- 5: Vocabulary, structures, and sentence length all match the band "
    "consistently.\n"
    "- 3: Mostly band-appropriate but drifts up (uses subjunctive at A2) "
    "or down (uses A1 forms at B2) noticeably in one or two turns.\n"
    "- 1: Persistent register mismatch - the agent talks above or below "
    "the learner's level for most of the session.\n\n"
    "**recast_naturalness** - when the learner errs, does the correction "
    "feel like natural conversation?\n"
    "- 5: Corrections appear as woven-in reformulations; the learner "
    "could miss them as corrections at all.\n"
    "- 3: Recasts are present but slightly stiff (e.g. the agent "
    "emphasizes the corrected form, or echoes too closely).\n"
    "- 1: Explicit metalinguistic corrections (\"se dice 'estoy', no "
    "'soy'\"), or the agent ignores errors entirely with no recast.\n\n"
    "**learner_production_space** - how much of the conversation is "
    "learner-produced vs. agent-produced?\n"
    "- 5: The agent elicits more than it lectures; turns are short and "
    "end in open questions.\n"
    "- 3: Mixed - some elicitation, some monologuing.\n"
    "- 1: The agent dominates with long explanations, multi-question "
    "turns, or completes the learner's sentences.\n\n"
    "**coherence** - does the session stay on the scenario topic, and "
    "does the agent remember turn-over-turn?\n"
    "- 5: Stays on scenario; the agent references things the learner "
    "said earlier.\n"
    "- 3: Mostly on scenario but the agent ignores or forgets a "
    "learner-introduced detail.\n"
    "- 1: The agent loses the thread, contradicts something the learner "
    "said, or jumps off-scenario without motivation.\n\n"
    "For `stop_reason`, choose exactly one:\n"
    "- `budget_reached`: the conversation was developing normally and "
    "ran to its turn budget.\n"
    "- `agent_derailed`: the agent's behavior visibly broke down "
    "(hallucinations, register collapse, tool-call spam, English drift).\n"
    "- `learner_abandoned`: the learner stopped engaging meaningfully "
    "(one-word replies repeated, gave up, switched fully to English in "
    "frustration).\n\n"
    "Respond with JSON matching the schema. Provide one short sentence "
    "(under 25 words) per dimension in the `rationale` map, keyed by "
    "dimension name. Be specific about which turn(s) drove the score."
)


class Rationale(BaseModel):
    """One short sentence per dimension. All fields required."""

    pedagogical_flow: str = Field(min_length=1)
    level_consistency: str = Field(min_length=1)
    recast_naturalness: str = Field(min_length=1)
    learner_production_space: str = Field(min_length=1)
    coherence: str = Field(min_length=1)


class SessionVerdict(BaseModel):
    pedagogical_flow: int = Field(ge=1, le=5)
    level_consistency: int = Field(ge=1, le=5)
    recast_naturalness: int = Field(ge=1, le=5)
    learner_production_space: int = Field(ge=1, le=5)
    coherence: int = Field(ge=1, le=5)
    rationale: Rationale
    stop_reason: Literal["budget_reached", "agent_derailed", "learner_abandoned"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall(self) -> float:
        dims = [
            self.pedagogical_flow,
            self.level_consistency,
            self.recast_naturalness,
            self.learner_production_space,
            self.coherence,
        ]
        return round(sum(dims) / len(dims), 2)


def _judge_cache_key(persona_id: str, transcript: list[ConversationTurn]) -> str:
    raw = (
        f"{JUDGE_SYSTEM_VERSION}|{persona_id}|{canonical_transcript(transcript)}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_judge_user_prompt(
    persona: Persona, transcript: list[ConversationTurn]
) -> str:
    formatted_turns: list[str] = []
    for i, t in enumerate(transcript, start=1):
        speaker = "AGENT" if t.role == "assistant" else "LEARNER"
        formatted_turns.append(f"[{i:02d}] {speaker}: {t.content}")
    transcript_block = "\n".join(formatted_turns)
    return (
        f"Persona:\n"
        f"- id: {persona.id}\n"
        f"- CEFR band: {persona.cefr_band}\n"
        f"- Scenario: {persona.scenario_domain}\n"
        f"- Authored error patterns: {', '.join(persona.error_patterns)}\n"
        f"- L1 reliance: {persona.L1_reliance:.2f}\n"
        f"- Fluency signal: {persona.fluency_signal}\n\n"
        f"Transcript ({len(transcript)} turns):\n"
        f"{transcript_block}\n\n"
        f"Score the session per the rubrics in your instructions and return "
        f"the JSON verdict."
    )


async def judge_session(
    client: anthropic.AsyncAnthropic,
    persona: Persona,
    transcript: list[ConversationTurn],
    *,
    cache: JsonDiskCache,
    model: str = DEFAULT_JUDGE_MODEL,
) -> SessionVerdict:
    key = _judge_cache_key(persona.id, transcript)
    cached = cache.get(key)
    if cached:
        return SessionVerdict.model_validate(cached)

    user_prompt = build_judge_user_prompt(persona, transcript)
    response = await client.messages.parse(
        model=model,
        max_tokens=2048,
        system=[cached_system_block(JUDGE_SYSTEM)],
        messages=[{"role": "user", "content": user_prompt}],
        output_format=SessionVerdict,
    )
    if response.parsed_output is None:
        raise RuntimeError(
            f"Opus did not return a parseable SessionVerdict for "
            f"persona {persona.id!r}; transcript len={len(transcript)}."
        )
    verdict: SessionVerdict = response.parsed_output
    cache.put(key, verdict.model_dump())
    return verdict
