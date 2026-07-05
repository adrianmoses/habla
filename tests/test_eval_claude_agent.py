"""Offline tests for the eval Claude caller/adapter (spec 012).

`call_claude` must collect text blocks into the spoken reply and adapt each
`tool_use` block to the `{"name", "arguments"}` shape
`eval.scoring.turn.parse_tool_calls` consumes — no network.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from eval.claude_agent import call_claude
from eval.scoring.turn import parse_tool_calls

LOG_TURN_ARGS: dict[str, Any] = {
    "learner_utterance": "Yo es Juan.",
    "errors": [{"type": "ser_estar", "produced": "es", "target": "soy"}],
    "fluency_signal": "moderate",
    "L1_used": False,
    "cefr_band": "A1",
}


def _fake_client(blocks: list[Any]) -> Any:
    response = SimpleNamespace(content=blocks)
    return SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=response))
    )


async def _call(blocks: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    return await call_claude(
        _fake_client(blocks),
        model="claude-sonnet-4-6",
        system="s",
        messages=[{"role": "user", "content": "Yo es Juan."}],
        max_tokens=256,
    )


async def test_collects_text_and_adapts_tool_use() -> None:
    text, calls = await _call(
        [
            SimpleNamespace(type="text", text="Hola Juan. "),
            SimpleNamespace(type="text", text="¿De dónde eres?"),
            SimpleNamespace(type="tool_use", name="log_turn", input=LOG_TURN_ARGS),
        ]
    )
    assert text == "Hola Juan. ¿De dónde eres?"
    assert calls == [{"name": "log_turn", "arguments": LOG_TURN_ARGS}]


async def test_adapted_call_flows_through_parse_tool_calls() -> None:
    text, calls = await _call(
        [
            SimpleNamespace(type="text", text="¡Hola!"),
            SimpleNamespace(type="tool_use", name="log_turn", input=LOG_TURN_ARGS),
        ]
    )
    parsed = parse_tool_calls(text, calls)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "log_turn"
    assert parsed[0]["arguments"]["cefr_band"] == "A1"


async def test_no_tool_use_returns_empty_calls() -> None:
    text, calls = await _call([SimpleNamespace(type="text", text="solo texto")])
    assert text == "solo texto"
    assert calls == []
