"""Judge prompt rendering + SessionVerdict shape tests (no network)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from eval.agent._cache import JsonDiskCache
from eval.agent.opus_judge import (
    JUDGE_SYSTEM,
    JUDGE_SYSTEM_VERSION,
    SessionVerdict,
    _judge_cache_key,
    build_judge_user_prompt,
    judge_session,
)
from eval.agent.personas.schema import Persona
from eval.fixtures.schema import ConversationTurn


def _persona() -> Persona:
    return Persona.model_validate(
        {
            "id": "judge_test",
            "cefr_band": "A2",
            "scenario_domain": "en el restaurante",
            "error_patterns": ["gender_agreement"],
            "L1_reliance": 0.3,
            "fluency_signal": "moderate",
        }
    )


def _transcript() -> list[ConversationTurn]:
    return [
        ConversationTurn(role="assistant", content="Buenos días. ¿Mesa para cuántos?"),
        ConversationTurn(role="user", content="Para dos persona, por favor."),
        ConversationTurn(role="assistant", content="Para dos personas, claro."),
    ]


def test_session_verdict_validates_bounds() -> None:
    v = SessionVerdict.model_validate(
        {
            "pedagogical_flow": 4,
            "level_consistency": 3,
            "recast_naturalness": 5,
            "learner_production_space": 3,
            "coherence": 4,
            "rationale": {
                "pedagogical_flow": "ok",
                "level_consistency": "ok",
                "recast_naturalness": "ok",
                "learner_production_space": "ok",
                "coherence": "ok",
            },
            "stop_reason": "budget_reached",
        }
    )
    assert v.overall == pytest.approx((4 + 3 + 5 + 3 + 4) / 5)


def test_session_verdict_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        SessionVerdict.model_validate(
            {
                "pedagogical_flow": 6,
                "level_consistency": 3,
                "recast_naturalness": 3,
                "learner_production_space": 3,
                "coherence": 3,
                "rationale": {},
                "stop_reason": "budget_reached",
            }
        )


def test_session_verdict_rejects_unknown_stop_reason() -> None:
    with pytest.raises(ValidationError):
        SessionVerdict.model_validate(
            {
                "pedagogical_flow": 3,
                "level_consistency": 3,
                "recast_naturalness": 3,
                "learner_production_space": 3,
                "coherence": 3,
                "rationale": {},
                "stop_reason": "something_else",
            }
        )


def test_overall_round_trips_through_dump() -> None:
    v = SessionVerdict.model_validate(
        {
            "pedagogical_flow": 4,
            "level_consistency": 4,
            "recast_naturalness": 4,
            "learner_production_space": 4,
            "coherence": 4,
            "rationale": {
                "pedagogical_flow": "ok",
                "level_consistency": "ok",
                "recast_naturalness": "ok",
                "learner_production_space": "ok",
                "coherence": "ok",
            },
            "stop_reason": "budget_reached",
        }
    )
    dumped = v.model_dump()
    assert dumped["overall"] == 4.0
    rebuilt = SessionVerdict.model_validate(dumped)
    assert rebuilt.overall == 4.0


def test_judge_user_prompt_includes_persona_and_numbered_turns() -> None:
    prompt = build_judge_user_prompt(_persona(), _transcript())
    assert "judge_test" in prompt
    assert "A2" in prompt
    assert "gender_agreement" in prompt
    assert "[01] AGENT" in prompt
    assert "[02] LEARNER" in prompt
    assert "[03] AGENT" in prompt
    assert "Para dos persona" in prompt


def test_judge_system_prompt_mentions_all_dims_and_stop_reason() -> None:
    # Bumping JUDGE_SYSTEM_VERSION invalidates the on-disk verdict cache.
    assert JUDGE_SYSTEM_VERSION
    assert "pedagogical_flow" in JUDGE_SYSTEM
    assert "level_consistency" in JUDGE_SYSTEM
    assert "recast_naturalness" in JUDGE_SYSTEM
    assert "learner_production_space" in JUDGE_SYSTEM
    assert "coherence" in JUDGE_SYSTEM
    assert "stop_reason" in JUDGE_SYSTEM


def test_cache_key_changes_with_transcript_perturbation() -> None:
    persona = _persona()
    base = _transcript()
    perturbed = [*base[:-1], ConversationTurn(role="assistant", content="distinto")]
    assert _judge_cache_key(persona.id, base) != _judge_cache_key(
        persona.id, perturbed
    )


def test_cache_key_stable_for_same_inputs() -> None:
    persona = _persona()
    base = _transcript()
    assert _judge_cache_key(persona.id, base) == _judge_cache_key(persona.id, base)


async def test_judge_session_cache_hit_skips_api_call(tmp_path: Path) -> None:
    """A cache hit must not touch the Anthropic client."""
    cache = JsonDiskCache(tmp_path, key_prefix="judge_")
    persona = _persona()
    transcript = _transcript()
    cache.put(
        _judge_cache_key(persona.id, transcript),
        SessionVerdict.model_validate(
            {
                "pedagogical_flow": 5,
                "level_consistency": 4,
                "recast_naturalness": 4,
                "learner_production_space": 3,
                "coherence": 4,
                "rationale": {
                    "pedagogical_flow": "cached",
                    "level_consistency": "cached",
                    "recast_naturalness": "cached",
                    "learner_production_space": "cached",
                    "coherence": "cached",
                },
                "stop_reason": "budget_reached",
            }
        ).model_dump(),
    )

    client = MagicMock()
    client.messages.parse = AsyncMock(
        side_effect=AssertionError("API hit on cached call")
    )

    verdict = await judge_session(client, persona, transcript, cache=cache)
    assert verdict.pedagogical_flow == 5
    assert verdict.overall == pytest.approx((5 + 4 + 4 + 3 + 4) / 5)
    client.messages.parse.assert_not_called()
