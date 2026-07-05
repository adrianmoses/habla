"""Parse `log_turn` from the LLM stream, dispatch to the sink, strip from TTS.

Buffers every `LLMTextFrame` between `LLMFullResponseStartFrame` and
`LLMFullResponseEndFrame`. On end:

1. Parse every tool call out of the buffered text (supports both
   `log_turn({...})` and `[TOOL_CALL: log_turn]{...}` surface forms).
2. For each `log_turn`, normalise to the canonical 4-key payload and dispatch
   as a :class:`TurnObservation` to the sink. Malformed or missing calls
   increment ``sink.missing``.
3. Emit a single cleaned `LLMTextFrame` with all tool-call syntax stripped so
   the tool text never reaches TTS.
"""

from __future__ import annotations

import logging

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from eval.scoring.turn import parse_tool_calls, strip_tool_calls
from hable_ya.learner.ingest import TurnIngestService
from hable_ya.pipeline.prompts.render import normalize_runtime_log_turn_args
from hable_ya.runtime.observations import TurnObservation, TurnObservationSink

logger = logging.getLogger("hable_ya.pipeline.tool_handler")


class HableYaToolHandler(FrameProcessor):
    def __init__(
        self,
        sink: TurnObservationSink,
        session_id: str,
        *,
        ingest: TurnIngestService | None = None,
    ) -> None:
        super().__init__()
        self._sink = sink
        self._session_id = session_id
        self._ingest = ingest
        self._buffer: list[str] = []
        self._buffering: bool = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer = []
            self._buffering = True
            logger.debug("session %s: LLM response start", self._session_id)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            if self._buffering:
                await self._flush(direction)
                self._buffering = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMTextFrame) and self._buffering:
            self._buffer.append(frame.text)
            return

        await self.push_frame(frame, direction)

    async def _flush(self, direction: FrameDirection) -> None:
        text = "".join(self._buffer)

        logger.debug(
            "session %s: LLM response end · %d chunks · %d chars · text=%r",
            self._session_id,
            len(self._buffer),
            len(text),
            text,
        )

        log_turn_calls = [
            call
            for call in parse_tool_calls(text, api_tool_calls=None)
            if call.get("name") == "log_turn"
        ]

        if not log_turn_calls:
            self._sink.missing += 1
            logger.warning(
                "session %s: model response missing log_turn call",
                self._session_id,
            )
        else:
            for call in log_turn_calls:
                raw_args = call.get("arguments", {})
                if not isinstance(raw_args, dict):
                    self._sink.missing += 1
                    logger.warning(
                        "session %s: log_turn arguments not a dict: %r",
                        self._session_id,
                        raw_args,
                    )
                    continue

                normalized = normalize_runtime_log_turn_args(raw_args)
                if normalized is None:
                    self._sink.missing += 1
                    logger.warning(
                        "session %s: log_turn args failed validation: %r",
                        self._session_id,
                        raw_args,
                    )
                    continue

                cefr_band = normalized.get("cefr_band")
                if cefr_band is None:
                    self._sink.band_missing += 1
                    logger.warning(
                        "session %s: log_turn omitted or invalid cefr_band: "
                        "raw=%r",
                        self._session_id,
                        raw_args.get("cefr_band"),
                    )
                obs = TurnObservation.now(
                    session_id=self._session_id,
                    learner_utterance=normalized["learner_utterance"],
                    errors=normalized["errors"],
                    fluency_signal=normalized["fluency_signal"],
                    L1_used=normalized["L1_used"],
                    cefr_band=cefr_band,
                )
                await self._sink.append(obs)
                if self._ingest is not None:
                    try:
                        await self._ingest.ingest(obs)
                    except Exception:
                        self._sink.ingest_failed += 1
                        logger.exception(
                            "session %s: learner DB ingest failed — "
                            "observation kept in JSONL only",
                            self._session_id,
                        )

        cleaned = strip_tool_calls(text)
        if cleaned:
            await self.push_frame(LLMTextFrame(cleaned), direction)
