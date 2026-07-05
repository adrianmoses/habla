"""Spike (spec 001, Step 1) — validate native Anthropic tool-calling in Pipecat.

Throwaway harness. Confirms, against the LIVE Anthropic API, the handful of
behaviors that source-reading alone can't fully settle before we rewrite the
runtime pipeline:

  (a) Claude co-emits spoken TEXT and a `log_turn` tool call in one turn
      (text must reach TTS; the tool call is a separate native block).
  (b) the registered `log_turn` handler fires with well-formed arguments.
  (c) a FunctionCallResultFrame is emitted after the handler answers.
  (d) the tool_use is answered by a tool_result written into the context
      (so the NEXT turn won't 400) AND run_llm=False suppresses a re-run.
  (e) thinking-disabled works despite pipecat always sending the
      `interleaved-thinking-2025-05-14` beta header.

Run:  ANTHROPIC_API_KEY must be set, or placed in habla/.env.
      uv run python scripts/spike_anthropic_tools.py

Exit code 0 = all checks passed (green light for the pipeline rewrite).
Non-zero = a live behavior diverged from the plan; see the spec's two-call
fallback (Key Decision 3) before proceeding.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    FunctionCallResultProperties,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.llm_service import FunctionCallParams

from hable_ya.tools.schema import HABLE_YA_TOOLS_SCHEMA

MODEL = "claude-sonnet-4-6"

SYSTEM = (
    "You are a Spanish conversation partner for a beginner (A2) learner. "
    "Reply in Spanish only, 1-2 short sentences with exactly one question. "
    "After your reply, call the log_turn tool exactly once to record a "
    "structured observation of the learner's last turn."
)
USER = "Hola, me llamo Ana. Yesterday I go to the store."


class Capture(FrameProcessor):
    """Records frames flowing past and signals when the turn is complete."""

    def __init__(self, done: asyncio.Event) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.in_progress: list[FunctionCallInProgressFrame] = []
        self.results: list[FunctionCallResultFrame] = []
        self._done = done

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            self.text_parts.append(frame.text)
        elif isinstance(frame, FunctionCallInProgressFrame):
            self.in_progress.append(frame)
        elif isinstance(frame, FunctionCallResultFrame):
            self.results.append(frame)
            self._done.set()
        elif isinstance(frame, LLMFullResponseEndFrame):
            # Fallback: if the model spoke but never called the tool, still stop.
            self._done.set()
        await self.push_frame(frame, direction)


async def main() -> int:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("FAIL: ANTHROPIC_API_KEY not set (env or habla/.env).")
        return 2

    context = LLMContext(
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        tools=HABLE_YA_TOOLS_SCHEMA,
    )
    aggregators = LLMContextAggregatorPair(context)

    llm = AnthropicLLMService(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=MODEL,
        params=AnthropicLLMService.InputParams(
            max_tokens=1024,
            thinking=AnthropicLLMService.ThinkingConfig(type="disabled"),
        ),
    )

    recorded: dict[str, object] = {}
    handler_called = asyncio.Event()

    async def handle_log_turn(params: FunctionCallParams) -> None:
        try:
            recorded.update(dict(params.arguments))
            handler_called.set()
        finally:
            await params.result_callback(
                {"status": "logged"},
                properties=FunctionCallResultProperties(run_llm=False),
            )

    llm.register_function("log_turn", handle_log_turn)

    done = asyncio.Event()
    capture = Capture(done)
    pipeline = Pipeline([llm, capture, aggregators.assistant()])
    task = PipelineTask(pipeline)

    runner = PipelineRunner(handle_sigint=False)
    run_task = asyncio.create_task(runner.run(task))
    await task.queue_frame(LLMContextFrame(context))

    try:
        await asyncio.wait_for(done.wait(), timeout=45)
    except TimeoutError:
        print("FAIL: timed out waiting for the turn to complete.")
    await asyncio.sleep(1.0)  # let result frame / context write settle
    await task.queue_frame(EndFrame())
    try:
        await asyncio.wait_for(run_task, timeout=15)
    except TimeoutError:
        run_task.cancel()

    spoken = "".join(capture.text_parts).strip()
    # After the assistant aggregator processes the turn, the context should
    # carry an assistant tool_use block and a matching tool_result — the pair
    # that keeps the NEXT turn from 400-ing.
    msgs = context.get_messages()
    tool_use = _find_block(msgs, "tool_use")
    tool_result = _find_block(msgs, "tool_result")

    print("--- spike results ---")
    print(f"(a) spoken text present : {bool(spoken)}  -> {spoken!r}")
    print(f"(b) handler fired w/ args: {handler_called.is_set()}  -> keys="
          f"{sorted(recorded)}")
    print(f"(c) result frame emitted : {len(capture.results) == 1}")
    print(f"(d) tool_use in context  : {tool_use is not None}")
    print(f"    tool_result in ctx    : {tool_result is not None}")
    print(f"(e) thinking-disabled run : {bool(spoken) or handler_called.is_set()} "
          f"(a completed call proves the beta-header coexistence)")

    ok = (
        bool(spoken)
        and handler_called.is_set()
        and {"learner_utterance", "fluency_signal", "L1_used"} <= set(recorded)
        and len(capture.results) == 1
        and tool_use is not None
        and tool_result is not None
    )
    verdict = (
        "PASS — green light for the rewrite"
        if ok
        else "FAIL — see spec Key Decision 3 fallback"
    )
    print(f"\n{verdict}")
    return 0 if ok else 1


def _find_block(messages: list, block_type: str) -> object | None:
    """Find the first content block of a given type across message contents."""
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == block_type:
                    return block
    return None


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
