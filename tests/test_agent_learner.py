"""SyntheticLearner unit tests (no network)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from eval.agent._cache import JsonDiskCache
from eval.agent.personas.schema import Persona
from eval.agent.synthetic_learner import (
    LEARNER_SYSTEM_VERSION,
    SyntheticLearner,
    _build_learner_system,
    _cache_key,
    _flip_for_learner,
)
from eval.fixtures.schema import ConversationTurn


def _persona(opening: str | None = None) -> Persona:
    return Persona.model_validate(
        {
            "id": "learner_test",
            "cefr_band": "A1",
            "scenario_domain": "pedir un café",
            "error_patterns": ["ser_estar"],
            "L1_reliance": 0.5,
            "fluency_signal": "weak",
            "opening_utterance": opening,
        }
    )


def test_system_prompt_mentions_band_scenario_and_errors() -> None:
    sys = _build_learner_system(_persona())
    assert "A1" in sys
    assert "pedir un café" in sys
    assert "ser_estar" in sys
    assert "50%" in sys  # L1_reliance 0.5 → 50%


def test_role_flip_swaps_assistant_and_user() -> None:
    transcript = [
        ConversationTurn(role="assistant", content="hola"),
        ConversationTurn(role="user", content="hi"),
        ConversationTurn(role="assistant", content="¿café?"),
    ]
    flipped = _flip_for_learner(transcript)
    assert [m["role"] for m in flipped] == ["user", "assistant", "user"]
    assert [m["content"] for m in flipped] == ["hola", "hi", "¿café?"]


def test_cache_key_differs_per_persona() -> None:
    transcript = [ConversationTurn(role="assistant", content="hola")]
    a = _cache_key("persona_a", transcript)
    b = _cache_key("persona_b", transcript)
    assert a != b


def test_cache_key_changes_when_transcript_grows() -> None:
    t1 = [ConversationTurn(role="assistant", content="hola")]
    t2 = [
        ConversationTurn(role="assistant", content="hola"),
        ConversationTurn(role="user", content="eh"),
    ]
    assert _cache_key("p", t1) != _cache_key("p", t2)


async def test_opening_utterance_short_circuit_skips_api(tmp_path: Path) -> None:
    persona = _persona(opening="Hola... eh... un café, please.")
    cache = JsonDiskCache(tmp_path, key_prefix="learner_")
    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=AssertionError("API hit when opening_utterance was set")
    )
    learner = SyntheticLearner(persona, client, cache=cache)
    out = await learner.next_utterance([])
    assert out == "Hola... eh... un café, please."
    client.messages.create.assert_not_called()


async def test_cache_hit_skips_api(tmp_path: Path) -> None:
    persona = _persona()
    cache = JsonDiskCache(tmp_path, key_prefix="learner_")
    transcript = [ConversationTurn(role="assistant", content="¿Qué tomas hoy?")]
    cache.put(
        _cache_key(persona.id, transcript),
        {"utterance": "Un café, please.", "system_version": LEARNER_SYSTEM_VERSION},
    )

    client = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=AssertionError("API hit on cached call")
    )
    learner = SyntheticLearner(persona, client, cache=cache)
    out = await learner.next_utterance(transcript)
    assert out == "Un café, please."
    client.messages.create.assert_not_called()


async def test_cache_miss_calls_api_and_caches_result(tmp_path: Path) -> None:
    persona = _persona()
    cache = JsonDiskCache(tmp_path, key_prefix="learner_")
    transcript = [ConversationTurn(role="assistant", content="¿Qué tomas hoy?")]

    fake_block = MagicMock()
    fake_block.type = "text"
    fake_block.text = "Un café... please."
    fake_response = MagicMock()
    fake_response.content = [fake_block]

    client = MagicMock()
    client.messages.create = AsyncMock(return_value=fake_response)
    learner = SyntheticLearner(persona, client, cache=cache)

    out = await learner.next_utterance(transcript)
    assert out == "Un café... please."
    client.messages.create.assert_awaited_once()
    # Subsequent call hits the cache (no further API call).
    client.messages.create.reset_mock()
    out2 = await learner.next_utterance(transcript)
    assert out2 == "Un café... please."
    client.messages.create.assert_not_called()
