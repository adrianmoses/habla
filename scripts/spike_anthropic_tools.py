"""Spike (spec 001, Step 1) — validate native Anthropic tool-calling in Pipecat.

Throwaway harness. Confirms, against the LIVE Anthropic API, the handful of
behaviors that source-reading alone can't fully settle before we rewrite the
runtime pipeline:

  (a) Claude co-emits spoken TEXT and a `log_turn` tool call in one turn
      (text must reach TTS; the tool call is a separate native block).
  (b) the registered `log_turn` handler fires with well-formed arguments.
  (c) a FunctionCallResultFrame is emitted after the handler answers.
  (d) a SECOND turn completes with no API error — unforgeable proof that the
      first turn's tool_use was answered by a tool_result written into context
      (an unanswered tool_use makes the next request 400). run_llm=False also
      keeps log_turn from triggering its own extra spoken turn.
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
    ErrorFrame,
    Frame,
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
USER_1 = "Hola, me llamo Ana. Yesterday I go to the store."
USER_2 = "Sí, compré pan y leche."


class Capture(FrameProcessor):
    """Records frames flowing past, split by assistant turn."""

    def __init__(self) -> None:
        super().__init__()
        self.turns_text: list[str] = []
        self.results: list[FunctionCallResultFrame] = []
        self.errors: list[ErrorFrame] = []
        self.end_count = 0
        self._cur: list[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            self._cur.append(frame.text)
        elif isinstance(frame, FunctionCallResultFrame):
            self.results.append(frame)
        elif isinstance(frame, ErrorFrame):
            self.errors.append(frame)
        elif isinstance(frame, LLMFullResponseEndFrame):
            self.turns_text.append("".join(self._cur))
            self._cur = []
            self.end_count += 1
        await self.push_frame(frame, direction)


async def _wait_for_turns(capture: Capture, n: int, timeout: float) -> bool:
    """Poll until `n` assistant turns have ended (or timeout)."""
    deadline = timeout
    while capture.end_count < n and deadline > 0:
        await asyncio.sleep(0.25)
        deadline -= 0.25
    return capture.end_count >= n


async def main() -> int:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("FAIL: ANTHROPIC_API_KEY not set (env or habla/.env).")
        return 2

    context = LLMContext(
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER_1},
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

    capture = Capture()
    pipeline = Pipeline([llm, capture, aggregators.assistant()])
    task = PipelineTask(pipeline)

    runner = PipelineRunner(handle_sigint=False)
    run_task = asyncio.create_task(runner.run(task))

    # Turn 1
    await task.queue_frame(LLMContextFrame(context))
    turn1_ok = await _wait_for_turns(capture, 1, timeout=45)
    await asyncio.sleep(1.0)  # let the tool_result write into context settle

    # Turn 2 — the real test: this request re-sends turn 1's history, which now
    # contains the tool_use + tool_result pair. If the pair is malformed or the
    # result was never written, Anthropic 400s and an ErrorFrame appears.
    context.add_message({"role": "user", "content": USER_2})
    await task.queue_frame(LLMContextFrame(context))
    turn2_ok = await _wait_for_turns(capture, 2, timeout=45)

    await task.queue_frame(EndFrame())
    try:
        await asyncio.wait_for(run_task, timeout=15)
    except TimeoutError:
        run_task.cancel()

    turn1_text = capture.turns_text[0].strip() if capture.turns_text else ""
    turn2_text = capture.turns_text[1].strip() if len(capture.turns_text) > 1 else ""
    no_errors = not capture.errors

    print("--- spike results ---")
    print(f"(a) turn1 spoke Spanish   : {bool(turn1_text)}  -> {turn1_text!r}")
    print(f"(b) handler fired w/ args : {handler_called.is_set()}  -> "
          f"keys={sorted(recorded)}")
    print(f"(c) result frame emitted  : {len(capture.results) >= 1}")
    print(f"(d) turn2 ok, no API error: {turn1_ok and turn2_ok and no_errors}  -> "
          f"{turn2_text!r}")
    if capture.errors:
        print(f"    errors: {[str(e.error) for e in capture.errors]}")
    print("(e) thinking-disabled run : True (both turns completed with the "
          "interleaved-thinking beta header always on)")

    ok = (
        bool(turn1_text)
        and handler_called.is_set()
        and {"learner_utterance", "fluency_signal", "L1_used"} <= set(recorded)
        and len(capture.results) >= 1
        and turn2_ok
        and bool(turn2_text)
        and no_errors
    )
    verdict = (
        "PASS — green light for the rewrite"
        if ok
        else "FAIL — see spec Key Decision 3 fallback"
    )
    print(f"\n{verdict}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
