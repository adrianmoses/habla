"""Claude agent-under-test caller for the eval harness (spec 012).

The runtime drives Claude through Pipecat; the eval harness calls the Anthropic
SDK directly, but with the SAME native `log_turn` tool contract, so eval measures
what production does. `call_claude` returns the spoken text plus the tool calls
adapted to the `{"name", "arguments"}` shape
`eval.scoring.turn.parse_tool_calls` consumes (its structured `api_tool_calls`
path) — the same adaptation the runtime's `log_turn` handler uses.
"""

from __future__ import annotations

from typing import Any

import anthropic

from hable_ya.tools.schema import LOG_TURN_ANTHROPIC_TOOL


async def call_claude(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float = 0.0,
) -> tuple[str, list[dict[str, Any]]]:
    """Call Claude with the native `log_turn` tool; return (text, tool_calls).

    No `thinking` param is sent, so extended thinking is off — the runtime's
    voice-latency posture. `tool_choice` is left unset (Anthropic default
    `auto`), matching the runtime: the model both replies and calls `log_turn`
    in one turn. `temperature` defaults to 0.0 for eval stability (the runtime
    uses 0.7; recast / `log_turn` behaviour is robust to it).
    """
    response = await client.messages.create(
        model=model,
        system=system,
        messages=messages,  # type: ignore[arg-type]
        tools=[LOG_TURN_ANTHROPIC_TOOL],  # type: ignore[list-item]
        max_tokens=max_tokens,
        temperature=temperature,
    )

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({"name": block.name, "arguments": block.input})

    return "".join(text_parts), tool_calls
