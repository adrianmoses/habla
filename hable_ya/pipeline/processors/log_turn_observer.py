"""Emission-rate accounting for native ``log_turn`` calls (spec 001).

With native tool-calling the ``log_turn`` dispatch happens in a registered
function handler (:mod:`hable_ya.pipeline.log_turn_handler`), which only fires
on turns that *called* the tool. To measure how often the model **omits** the
call — the metric that told us the on-device Gemma emitted on ~80% of turns —
we watch the assistant turn boundary.

Frame ordering is deterministic in ``AnthropicLLMService``: ``run_function_calls``
is awaited (emitting ``FunctionCallInProgressFrame`` downstream) *before* the
``LLMFullResponseEndFrame`` is pushed. So by the time a turn ends we already
know whether a ``log_turn`` call fired this turn — no race.

This observer only counts; it does not dispatch, answer, or touch the text
stream. ``sink.missing`` therefore counts turns with no *usable* observation:
this processor covers turns with no call at all, and the handler covers turns
whose call had malformed args — mutually exclusive per turn, so no double count.
"""

from __future__ import annotations

import logging

from pipecat.frames.frames import (
    Frame,
    FunctionCallInProgressFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from hable_ya.runtime.observations import TurnObservationSink
from hable_ya.tools.schema import LOG_TURN_NAME

logger = logging.getLogger("hable_ya.pipeline.log_turn_observer")


class LogTurnEmissionObserver(FrameProcessor):
    """Increment ``sink.missing`` for each assistant turn with no ``log_turn``."""

    def __init__(self, sink: TurnObservationSink) -> None:
        super().__init__()
        self._sink = sink
        self._log_turn_seen = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._log_turn_seen = False
        elif (
            isinstance(frame, FunctionCallInProgressFrame)
            and frame.function_name == LOG_TURN_NAME
        ):
            self._log_turn_seen = True
        elif isinstance(frame, LLMFullResponseEndFrame):
            if not self._log_turn_seen:
                self._sink.missing += 1
                logger.warning("assistant turn produced no log_turn call")

        await self.push_frame(frame, direction)
