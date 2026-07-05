"""Minimal turn logging placeholder.

Logs transcription frames (user turns) and LLM full-response-end frames
(assistant turns) to stdout so a live session produces a visible trace. Spec
026 replaces this with durable persistence against the learner DB.
"""

from __future__ import annotations

import logging

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger("hable_ya.turns")


class HableYaTurnObserver(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.finalized:
            logger.info("user: %s", frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            logger.info("assistant: <response complete>")

        await self.push_frame(frame, direction)
