"""Live judge_session smoke (skips without ANTHROPIC_API_KEY).

Schema-only assertion: the verdict comes back, scores are in 1–5, and
the cache file is written. Score values themselves are
non-deterministic; they're not asserted.
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
import pytest
from dotenv import load_dotenv

from eval.agent._cache import JsonDiskCache
from eval.agent.opus_judge import judge_session
from eval.agent.personas.schema import Persona
from eval.fixtures.schema import ConversationTurn

load_dotenv()
pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; skipping live smoke",
)


async def test_judge_returns_well_formed_verdict_for_canned_transcript(
    tmp_path: Path,
) -> None:
    persona = Persona.model_validate(
        {
            "id": "smoke_judge_a2",
            "cefr_band": "A2",
            "scenario_domain": "en el restaurante",
            "error_patterns": ["gender_agreement"],
            "L1_reliance": 0.3,
            "fluency_signal": "moderate",
        }
    )
    transcript = [
        ConversationTurn(
            role="assistant", content="Buenos días. ¿Mesa para cuántas personas?"
        ),
        ConversationTurn(role="user", content="Para dos persona, por favor."),
        ConversationTurn(
            role="assistant",
            content="Para dos personas, perfecto. ¿Tienen reserva?",
        ),
        ConversationTurn(role="user", content="No. ¿Es posible una mesa al ventana?"),
        ConversationTurn(
            role="assistant",
            content=(
                "Una mesa junto a la ventana, claro. Síganme, por favor. "
                "¿Qué les apetece beber?"
            ),
        ),
        ConversationTurn(
            role="user",
            content="Yo quiero un agua, sin gas. Y mi amigo... una cerveza.",
        ),
    ]

    cache = JsonDiskCache(tmp_path, key_prefix="judge_")
    client = anthropic.AsyncAnthropic()
    verdict = await judge_session(client, persona, transcript, cache=cache)

    for dim in [
        "pedagogical_flow",
        "level_consistency",
        "recast_naturalness",
        "learner_production_space",
        "coherence",
    ]:
        score = getattr(verdict, dim)
        assert 1 <= score <= 5
    assert verdict.stop_reason in {
        "budget_reached",
        "agent_derailed",
        "learner_abandoned",
    }
    assert 1.0 <= verdict.overall <= 5.0
    # Cache should now hold the verdict.
    assert any(p.suffix == ".json" for p in tmp_path.iterdir())

    # Re-judge — must hit the cache, not the API. We can't assert directly
    # without injecting a mock client, but the same call should return the
    # same scores.
    second = await judge_session(client, persona, transcript, cache=cache)
    assert second.model_dump() == verdict.model_dump()
