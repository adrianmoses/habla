"""Opus-driven simulated learner.

Plays a persona-conditioned Spanish-language learner against the served
agent. Each call to `next_utterance` consults the disk cache first; only
on a miss does an Anthropic API call fire. The cache key includes the
full transcript-so-far, so any agent-side change cascades a re-roll
(cached learner replies cannot mask agent regressions).

Role mapping: the runtime transcript records `assistant` for the agent
and `user` for the learner. From Opus's perspective (playing the
learner), what the agent said is the message Opus is responding to —
i.e. `user` from Opus's side. The transcript is flipped before being
sent to Anthropic.
"""

from __future__ import annotations

import hashlib
from typing import Final, Literal

import anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel

from eval.agent._cache import (
    JsonDiskCache,
    cached_system_block,
    canonical_transcript,
)
from eval.agent.personas.schema import Persona
from eval.fixtures.schema import ConversationTurn

LEARNER_SYSTEM_VERSION: Final[str] = "1"
DEFAULT_LEARNER_MODEL: Final[str] = "claude-opus-4-7"

_FLUENCY_DESCRIPTION = {
    "weak": "short, hesitant sentences with frequent pauses",
    "moderate": "complete sentences with some hesitations and self-corrections",
    "strong": "flowing sentences with confident vocabulary",
}


def _build_learner_system(persona: Persona) -> str:
    errors = ", ".join(persona.error_patterns)
    fluency_desc = _FLUENCY_DESCRIPTION[persona.fluency_signal]
    l1_pct = int(persona.L1_reliance * 100)
    return (
        f"You are roleplaying a Spanish language learner at CEFR band "
        f"{persona.cefr_band}.\n\n"
        f"You are talking with a Spanish tutor. The current scenario is: "
        f"{persona.scenario_domain}.\n\n"
        f"Your speech profile (stay in character):\n"
        f"- You consistently produce these kinds of grammatical errors as "
        f"you speak: {errors}. Don't acknowledge them or try to fix "
        f"yourself — a real learner doesn't notice these slips in real time.\n"
        f"- Roughly {l1_pct}% of the time you fall back to English when "
        f"you don't know a word (e.g. \"eh... what's the word for...\", "
        f"\"I want to say...\", or just code-switching mid-sentence).\n"
        f"- Your speech is {persona.fluency_signal}: {fluency_desc}.\n\n"
        f"Produce ONE natural learner turn responding to the tutor's most "
        f"recent message. Return ONLY the learner's words — no quotation "
        f"marks, no stage directions, no narration. Use Spanish where you "
        f"can and English where you must, with the realistic errors above. "
        f"Keep your turn to one or two sentences."
    )


def _cache_key(persona_id: str, transcript: list[ConversationTurn]) -> str:
    raw = (
        f"{LEARNER_SYSTEM_VERSION}|{persona_id}|"
        f"{canonical_transcript(transcript)}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _flip_for_learner(
    transcript: list[ConversationTurn],
) -> list[MessageParam]:
    out: list[MessageParam] = []
    for t in transcript:
        flipped_role: Literal["user", "assistant"] = (
            "user" if t.role == "assistant" else "assistant"
        )
        out.append({"role": flipped_role, "content": t.content})
    return out


class CachedLearnerResponse(BaseModel):
    utterance: str
    system_version: str


class SyntheticLearner:
    def __init__(
        self,
        persona: Persona,
        client: anthropic.AsyncAnthropic,
        *,
        cache: JsonDiskCache,
        model: str = DEFAULT_LEARNER_MODEL,
    ) -> None:
        self._persona = persona
        self._client = client
        self._cache = cache
        self._model = model

    @property
    def persona(self) -> Persona:
        return self._persona

    async def next_utterance(
        self, transcript: list[ConversationTurn]
    ) -> str:
        if not transcript and self._persona.opening_utterance:
            return self._persona.opening_utterance

        key = _cache_key(self._persona.id, transcript)
        cached = self._cache.get(key)
        if cached:
            return str(cached["utterance"])

        system = _build_learner_system(self._persona)
        messages: list[MessageParam]
        if transcript:
            messages = _flip_for_learner(transcript)
        else:
            messages = [
                {
                    "role": "user",
                    "content": (
                        "Comienza tú la conversación con un saludo o una "
                        "frase corta, en personaje."
                    ),
                }
            ]

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=256,
            temperature=1.0,
            system=[cached_system_block(system)],
            messages=messages,
        )
        utterance = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        self._cache.put(
            key,
            {"utterance": utterance, "system_version": LEARNER_SYSTEM_VERSION},
        )
        return utterance
