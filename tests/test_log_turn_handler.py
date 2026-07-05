"""Tests for native `log_turn` handling (spec 001).

Two pieces replace the old text-parsing `HableYaToolHandler`:

- `make_log_turn_handler` — the function registered on the LLM service; it
  dispatches the observation and answers the tool call (run_llm=False). It only
  runs on turns that *called* log_turn.
- `LogTurnEmissionObserver` — counts turns that produced *no* log_turn call
  (`sink.missing`), the emission-rate metric.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pipecat.frames.frames import (
    Frame,
    FunctionCallInProgressFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from hable_ya.pipeline.log_turn_handler import make_log_turn_handler
from hable_ya.pipeline.processors.log_turn_observer import LogTurnEmissionObserver
from hable_ya.runtime.observations import TurnObservationSink

GOOD_ARGS: dict[str, Any] = {
    "learner_utterance": "Yo es Juan.",
    "errors": [{"type": "ser_estar", "produced": "es", "target": "soy"}],
    "fluency_signal": "moderate",
    "L1_used": False,
    "cefr_band": "B1",
}


@pytest.fixture
def sink(tmp_path: Path) -> TurnObservationSink:
    return TurnObservationSink(tmp_path / "turns.jsonl", ring_size=10)


def _params(arguments: Any, result_callback: AsyncMock) -> FunctionCallParams:
    return FunctionCallParams(
        function_name="log_turn",
        tool_call_id="t1",
        arguments=arguments,
        llm=MagicMock(),
        context=MagicMock(),
        result_callback=result_callback,
    )


async def _run(handler: Any, arguments: Any) -> AsyncMock:
    cb = AsyncMock()
    await handler(_params(arguments, cb))
    return cb


def _assert_answered(cb: AsyncMock) -> None:
    """The tool call must always be answered with run_llm=False."""
    cb.assert_awaited_once()
    _, kwargs = cb.call_args
    assert kwargs["properties"].run_llm is False


# ---- make_log_turn_handler -------------------------------------------------


async def test_happy_path_dispatches_and_answers(sink: TurnObservationSink) -> None:
    handler = make_log_turn_handler(sink, "s1")
    cb = await _run(handler, dict(GOOD_ARGS))

    recent = sink.recent()
    assert len(recent) == 1
    obs = recent[0]
    assert obs.session_id == "s1"
    assert obs.learner_utterance == "Yo es Juan."
    assert obs.fluency_signal == "moderate"
    assert obs.L1_used is False
    assert obs.errors == [{"type": "ser_estar", "produced": "es", "target": "soy"}]
    assert obs.cefr_band == "B1"
    assert sink.missing == 0
    assert sink.band_missing == 0
    _assert_answered(cb)


async def test_missing_cefr_band_degrades(sink: TurnObservationSink) -> None:
    handler = make_log_turn_handler(sink, "s2")
    args = {k: v for k, v in GOOD_ARGS.items() if k != "cefr_band"}
    cb = await _run(handler, args)

    recent = sink.recent()
    assert len(recent) == 1
    assert recent[0].cefr_band is None
    assert sink.band_missing == 1
    assert sink.missing == 0
    _assert_answered(cb)


async def test_out_of_enum_cefr_band_degrades(sink: TurnObservationSink) -> None:
    handler = make_log_turn_handler(sink, "s3")
    cb = await _run(handler, {**GOOD_ARGS, "cefr_band": "intermediate"})
    assert sink.recent()[0].cefr_band is None
    assert sink.band_missing == 1
    _assert_answered(cb)


async def test_malformed_errors_dropped_but_answered(
    sink: TurnObservationSink,
) -> None:
    handler = make_log_turn_handler(sink, "s4")
    cb = await _run(handler, {**GOOD_ARGS, "errors": "not-a-list"})
    assert sink.recent() == []
    assert sink.missing == 1
    _assert_answered(cb)


async def test_invalid_fluency_dropped(sink: TurnObservationSink) -> None:
    handler = make_log_turn_handler(sink, "s5")
    cb = await _run(handler, {**GOOD_ARGS, "fluency_signal": "low"})
    assert sink.recent() == []
    assert sink.missing == 1
    _assert_answered(cb)


async def test_non_dict_arguments_dropped(sink: TurnObservationSink) -> None:
    handler = make_log_turn_handler(sink, "s6")
    cb = await _run(handler, "not-a-dict")
    assert sink.recent() == []
    assert sink.missing == 1
    _assert_answered(cb)


class _RecordingIngest:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[object] = []
        self.fail = fail

    async def ingest(self, obs: object) -> None:
        self.calls.append(obs)
        if self.fail:
            raise RuntimeError("simulated DB outage")


async def test_ingest_called_on_happy_path(sink: TurnObservationSink) -> None:
    ingest = _RecordingIngest()
    handler = make_log_turn_handler(sink, "si1", ingest=ingest)  # type: ignore[arg-type]
    cb = await _run(handler, dict(GOOD_ARGS))
    assert len(ingest.calls) == 1
    assert sink.ingest_failed == 0
    _assert_answered(cb)


async def test_ingest_failure_keeps_sink_and_still_answers(
    sink: TurnObservationSink,
) -> None:
    ingest = _RecordingIngest(fail=True)
    handler = make_log_turn_handler(sink, "si2", ingest=ingest)  # type: ignore[arg-type]
    cb = await _run(handler, dict(GOOD_ARGS))
    # Graceful degradation: JSONL sink still captured it; counter bumped; and
    # crucially the tool call is still answered so the next turn won't 400.
    assert len(sink.recent()) == 1
    assert sink.ingest_failed == 1
    assert sink.missing == 0
    _assert_answered(cb)


async def test_ingest_not_called_on_malformed(sink: TurnObservationSink) -> None:
    ingest = _RecordingIngest()
    handler = make_log_turn_handler(sink, "si3", ingest=ingest)  # type: ignore[arg-type]
    await _run(handler, {**GOOD_ARGS, "errors": "not-a-list"})
    assert ingest.calls == []
    assert sink.missing == 1
    assert sink.ingest_failed == 0


# ---- LogTurnEmissionObserver ----------------------------------------------


async def _drive(observer: LogTurnEmissionObserver, frames: list[Frame]) -> None:
    async def capture(
        frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM
    ) -> None:
        return None

    observer.push_frame = capture  # type: ignore[method-assign]
    for f in frames:
        await observer.process_frame(f, FrameDirection.DOWNSTREAM)


async def test_observer_counts_missing_when_no_call(sink: TurnObservationSink) -> None:
    observer = LogTurnEmissionObserver(sink)
    await _drive(
        observer,
        [LLMFullResponseStartFrame(), LLMFullResponseEndFrame()],
    )
    assert sink.missing == 1


async def test_observer_no_miss_when_log_turn_fired(
    sink: TurnObservationSink,
) -> None:
    observer = LogTurnEmissionObserver(sink)
    await _drive(
        observer,
        [
            LLMFullResponseStartFrame(),
            FunctionCallInProgressFrame(
                function_name="log_turn", tool_call_id="t1", arguments={}
            ),
            LLMFullResponseEndFrame(),
        ],
    )
    assert sink.missing == 0


async def test_observer_counts_per_turn(sink: TurnObservationSink) -> None:
    observer = LogTurnEmissionObserver(sink)
    await _drive(
        observer,
        [
            # Turn 1: with a call → no miss.
            LLMFullResponseStartFrame(),
            FunctionCallInProgressFrame(
                function_name="log_turn", tool_call_id="t1", arguments={}
            ),
            LLMFullResponseEndFrame(),
            # Turn 2: no call → one miss.
            LLMFullResponseStartFrame(),
            LLMFullResponseEndFrame(),
        ],
    )
    assert sink.missing == 1


async def test_observer_ignores_other_function_calls(
    sink: TurnObservationSink,
) -> None:
    observer = LogTurnEmissionObserver(sink)
    await _drive(
        observer,
        [
            LLMFullResponseStartFrame(),
            FunctionCallInProgressFrame(
                function_name="something_else", tool_call_id="t1", arguments={}
            ),
            LLMFullResponseEndFrame(),
        ],
    )
    assert sink.missing == 1
