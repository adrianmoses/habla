"""Live smoke: the Claude model-under-test emits a native `log_turn` (spec 012).

Opt-in — skipped without ANTHROPIC_API_KEY, like the other eval smokes. There are
no committed fixture JSONs (they're batch-generated), so this drives the
`call_claude` path directly with a rendered native-tool prompt rather than a
fixture. It's the real proof Claude both replies in Spanish and calls `log_turn`
as a native tool under the eval prompt.
"""

from __future__ import annotations

import os

import pytest

from eval.claude_agent import call_claude
from eval.fixtures.schema import LearnerProfile, SystemParams
from hable_ya.config import settings
from hable_ya.learner.themes import NEUTRAL_THEME
from hable_ya.pipeline.prompts.render import render_system_prompt

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"), reason="requires ANTHROPIC_API_KEY"
)


async def test_claude_under_test_emits_native_log_turn() -> None:
    import anthropic

    profile = LearnerProfile(
        production_level=0.3,
        L1_reliance=0.5,
        speech_fluency=0.5,
        is_calibrated=False,
        sessions_completed=0,
        vocab_strengths=[],
        error_patterns=[],
    )
    system = render_system_prompt(
        SystemParams(profile=profile, theme=NEUTRAL_THEME),
        band="A2",
        tool_mode="native",
    )
    client = anthropic.AsyncAnthropic()
    text, calls = await call_claude(
        client,
        model=settings.llm_model_name,
        system=system,
        messages=[
            {
                "role": "user",
                "content": "Hola, me llamo Ana. Yesterday I go to the store.",
            }
        ],
        max_tokens=1024,
    )

    assert text.strip(), "model produced no spoken reply"
    log_turn = next((c for c in calls if c["name"] == "log_turn"), None)
    assert log_turn is not None, "model did not emit a native log_turn tool call"
    assert "learner_utterance" in log_turn["arguments"]
