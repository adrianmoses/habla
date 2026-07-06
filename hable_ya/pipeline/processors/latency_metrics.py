"""Per-stage latency observer (spec #013).

`PipelineParams(enable_metrics=True)` makes each service emit a `MetricsFrame`
carrying `TTFBMetricsData(processor, value)` — the time-to-first-byte for that
service on the turn. The pipeline's `UserBotLatencyObserver` reports only the
end-to-end number; this observer captures the STT / LLM / TTS *split* so a
latency regression can be localized to one hop.

Log-only, gated on `settings.latency_debug` at the wiring site
(`hable_ya.pipeline.runner`). A `MetricsFrame` is pushed through every
downstream hop, so the same frame is observed many times per turn — we dedup by
frame identity with a bounded ring so each TTFB is logged once.
"""

from __future__ import annotations

import logging
from collections import deque

from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed

latency_logger = logging.getLogger("hable_ya.latency")

# Substrings that appear in the service class names Pipecat uses as the metric
# `processor` (e.g. "OpenAISTTService#0", "AnthropicLLMService#0",
# "CartesiaTTSService#0"). Order matters only for readability; the substrings
# are mutually exclusive across the three services.
_STAGE_BY_SUBSTRING: tuple[tuple[str, str], ...] = (
    ("STT", "stt"),
    ("LLM", "llm"),
    ("TTS", "tts"),
)

_SEEN_RING_SIZE = 256


def stage_for_processor(processor: str) -> str | None:
    """Map a metric `processor` name to a pipeline stage, or None if unknown."""
    for needle, stage in _STAGE_BY_SUBSTRING:
        if needle in processor:
            return stage
    return None


class PerStageLatencyObserver(BaseObserver):
    """Records + logs per-service TTFB from `MetricsFrame`s, once per turn.

    Each captured `(stage, ttfb_ms)` is appended to `self.records` (a bounded
    ring) and logged under `hable_ya.latency`. The `records` attribute is the
    programmatic view — tests assert on it rather than on log output, which is
    unreliable to capture once a global `logging.disable` is in effect.
    """

    def __init__(self) -> None:
        super().__init__()
        self._seen: deque[int] = deque(maxlen=_SEEN_RING_SIZE)
        self._seen_set: set[int] = set()
        self.records: deque[tuple[str, int]] = deque(maxlen=_SEEN_RING_SIZE)

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if not isinstance(frame, MetricsFrame):
            return
        # Dedup on the frame's own process-unique id (not Python's id(), which
        # is reused once a short-lived frame is GC'd). One MetricsFrame is
        # pushed through every downstream hop; we record its TTFB once.
        frame_id = frame.id
        if frame_id in self._seen_set:
            return
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(frame_id)
        self._seen_set.add(frame_id)

        for metric in frame.data:
            if not isinstance(metric, TTFBMetricsData):
                continue
            stage = stage_for_processor(metric.processor)
            if stage is None:
                continue
            ttfb_ms = int(metric.value * 1000)
            self.records.append((stage, ttfb_ms))
            latency_logger.info(
                "stage=%s ttfb_ms=%d processor=%s",
                stage,
                ttfb_ms,
                metric.processor,
            )
