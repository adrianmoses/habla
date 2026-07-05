"""Live SyntheticLearner smoke (skips without ANTHROPIC_API_KEY).

Asserts shape + non-empty Spanish output, never specific content — Opus
is non-deterministic at the persona level. The point is that the wiring
holds end-to-end against a real key.
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
import pytest
from dotenv import load_dotenv

from eval.agent._cache import JsonDiskCache
from eval.agent.personas.schema import Persona
from eval.agent.synthetic_learner import SyntheticLearner
from eval.fixtures.schema import ConversationTurn

load_dotenv()
pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; skipping live smoke",
)


async def test_learner_responds_to_a_single_agent_turn(tmp_path: Path) -> None:
    persona = Persona.model_validate(
        {
            "id": "smoke_a1_cafeteria",
            "cefr_band": "A1",
            "scenario_domain": "pedir un café",
            "error_patterns": ["ser_estar"],
            "L1_reliance": 0.5,
            "fluency_signal": "weak",
        }
    )
    cache = JsonDiskCache(tmp_path, key_prefix="learner_")
    client = anthropic.AsyncAnthropic()
    learner = SyntheticLearner(persona, client, cache=cache)

    transcript = [
        ConversationTurn(role="assistant", content="¡Hola! ¿Qué quieres tomar hoy?")
    ]
    out = await learner.next_utterance(transcript)
    assert isinstance(out, str)
    assert out.strip()
    # Cache should now hold the result.
    assert any(p.suffix == ".json" for p in tmp_path.iterdir())
