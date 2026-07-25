"""Tests for the learner response-latency observer (spec #024).

Offline only — the observer is fed synthetic FramePushed events so the anchor
state machine (barge-in guard, multi-part replies, one-shot measurement, VAD
back-correction) is exercised without a running pipeline, and the `log_turn`
handler is exercised with a pre-loaded observer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    TextFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.services.llm_service import FunctionCallParams

from hable_ya.pipeline.log_turn_handler import make_log_turn_handler
from hable_ya.pipeline.processors.response_latency import ResponseLatencyObserver
from hable_ya.runtime.observations import TurnObservationSink


def _pushed(frame: object) -> FramePushed:
    return FramePushed(
        source=MagicMock(),
        destination=MagicMock(),
        frame=frame,  # type: ignore[arg-type]
        direction=MagicMock(),
        timestamp=0,
    )


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Deterministic wall clock: `clock[0]` is what `time.time()` returns."""
    now = [100.0]
    monkeypatch.setattr(
        "hable_ya.pipeline.processors.response_latency.time.time",
        lambda: now[0],
    )
    return now


def _user_start(timestamp: float, start_secs: float = 0.25) -> FramePushed:
    return _pushed(
        VADUserStartedSpeakingFrame(timestamp=timestamp, start_secs=start_secs)
    )


class TestObserver:
    async def test_happy_path_with_vad_back_correction(
        self, clock: list[float]
    ) -> None:
        obs = ResponseLatencyObserver()
        clock[0] = 100.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        # VAD confirmed at 102.0 after a 0.5s window → true onset 101.5.
        await obs.on_push_frame(_user_start(timestamp=102.0, start_secs=0.5))
        assert list(obs.records) == [1500]
        assert obs.pending_ms == 1500

    async def test_no_anchor_on_first_turn(self, clock: list[float]) -> None:
        obs = ResponseLatencyObserver()
        await obs.on_push_frame(_user_start(timestamp=102.0))
        assert list(obs.records) == []
        assert obs.pending_ms is None

    async def test_barge_in_never_arms(self, clock: list[float]) -> None:
        obs = ResponseLatencyObserver()
        clock[0] = 100.0
        await obs.on_push_frame(_pushed(BotStartedSpeakingFrame()))
        # Learner interrupts while the bot speaks; the bot's stop is caused by
        # the barge-in, so it must not become an anchor.
        await obs.on_push_frame(_user_start(timestamp=100.5))
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        await obs.on_push_frame(_pushed(VADUserStoppedSpeakingFrame()))
        # Learner speaks again before the tutor does → still nothing to measure.
        await obs.on_push_frame(_user_start(timestamp=105.0))
        assert list(obs.records) == []
        assert obs.pending_ms is None

    async def test_multi_part_reply_measures_from_final_stop(
        self, clock: list[float]
    ) -> None:
        obs = ResponseLatencyObserver()
        clock[0] = 100.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        await obs.on_push_frame(_pushed(BotStartedSpeakingFrame()))  # bot resumes
        clock[0] = 110.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        await obs.on_push_frame(_user_start(timestamp=110.75, start_secs=0.25))
        assert list(obs.records) == [500]

    async def test_anchor_is_one_shot(self, clock: list[float]) -> None:
        obs = ResponseLatencyObserver()
        clock[0] = 100.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        await obs.on_push_frame(_user_start(timestamp=101.0))
        # Mid-turn pause + resume: second onset must not measure again.
        await obs.on_push_frame(_pushed(VADUserStoppedSpeakingFrame()))
        await obs.on_push_frame(_user_start(timestamp=103.0))
        assert len(obs.records) == 1

    async def test_negative_latency_discarded(self, clock: list[float]) -> None:
        obs = ResponseLatencyObserver()
        clock[0] = 100.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        # Back-corrected onset lands before the anchor (VAD window overlapped
        # the bot's tail) → discard rather than record a negative.
        await obs.on_push_frame(_user_start(timestamp=100.25, start_secs=0.5))
        assert list(obs.records) == []
        assert obs.pending_ms is None

    async def test_dedups_same_frame(self, clock: list[float]) -> None:
        obs = ResponseLatencyObserver()
        clock[0] = 100.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        frame = VADUserStartedSpeakingFrame(timestamp=101.5, start_secs=0.5)
        # Same frame observed at multiple hops → measured once.
        await obs.on_push_frame(_pushed(frame))
        await obs.on_push_frame(_pushed(frame))
        assert list(obs.records) == [1000]

    async def test_ignores_unrelated_frames(self, clock: list[float]) -> None:
        obs = ResponseLatencyObserver()
        await obs.on_push_frame(_pushed(TextFrame(text="hola")))
        assert list(obs.records) == []

    async def test_pop_is_consume_once(self, clock: list[float]) -> None:
        obs = ResponseLatencyObserver()
        clock[0] = 100.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        await obs.on_push_frame(_user_start(timestamp=101.0, start_secs=0.5))
        assert obs.pop() == 500
        assert obs.pop() is None

    async def test_new_measurement_overwrites_unconsumed(
        self, clock: list[float]
    ) -> None:
        obs = ResponseLatencyObserver()
        clock[0] = 100.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        await obs.on_push_frame(_user_start(timestamp=101.0, start_secs=0.5))
        # A turn whose log_turn never fired leaves 500 unconsumed; the next
        # cycle's measurement replaces it so it can't leak onto a later turn.
        await obs.on_push_frame(_pushed(VADUserStoppedSpeakingFrame()))
        await obs.on_push_frame(_pushed(BotStartedSpeakingFrame()))
        clock[0] = 110.0
        await obs.on_push_frame(_pushed(BotStoppedSpeakingFrame()))
        await obs.on_push_frame(_user_start(timestamp=111.25, start_secs=0.25))
        assert obs.pending_ms == 1000
        assert list(obs.records) == [500, 1000]


# ---- log_turn handler integration ------------------------------------------

GOOD_ARGS: dict[str, Any] = {
    "learner_utterance": "Yo es Juan.",
    "errors": [],
    "fluency_signal": "moderate",
    "L1_used": False,
    "cefr_band": "B1",
}


async def _run(handler: Any, arguments: Any) -> AsyncMock:
    cb = AsyncMock()
    await handler(
        FunctionCallParams(
            function_name="log_turn",
            tool_call_id="t1",
            arguments=arguments,
            llm=MagicMock(),
            context=MagicMock(),
            result_callback=cb,
        )
    )
    return cb


@pytest.fixture
def sink(tmp_path: Path) -> TurnObservationSink:
    return TurnObservationSink(tmp_path / "turns.jsonl", ring_size=10)


async def test_handler_consumes_pending_into_extra(
    sink: TurnObservationSink,
) -> None:
    latency = ResponseLatencyObserver()
    latency.pending_ms = 850
    handler = make_log_turn_handler(sink, "s1", latency=latency)
    await _run(handler, dict(GOOD_ARGS))

    assert sink.recent()[0].extra == {"response_latency_ms": 850}
    assert latency.pending_ms is None


async def test_handler_no_pending_leaves_extra_empty(
    sink: TurnObservationSink,
) -> None:
    latency = ResponseLatencyObserver()
    handler = make_log_turn_handler(sink, "s2", latency=latency)
    await _run(handler, dict(GOOD_ARGS))

    assert sink.recent()[0].extra == {}


async def test_handler_without_observer_unchanged(
    sink: TurnObservationSink,
) -> None:
    handler = make_log_turn_handler(sink, "s3")
    await _run(handler, dict(GOOD_ARGS))

    assert sink.recent()[0].extra == {}
