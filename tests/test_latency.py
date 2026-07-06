"""Tests for the #013 latency stats + per-stage observer.

Offline only — no live API. The observer is fed synthetic MetricsFrames so the
capture/dedup/stage-mapping logic is exercised without a running pipeline.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pipecat.frames.frames import MetricsFrame, TextFrame
from pipecat.metrics.metrics import ProcessingMetricsData, TTFBMetricsData
from pipecat.observers.base_observer import FramePushed

from hable_ya.pipeline.processors.latency_metrics import (
    PerStageLatencyObserver,
    stage_for_processor,
)
from hable_ya.runtime.latency import LatencyStats, percentile, summarize


class TestStats:
    def test_percentile_interpolates(self) -> None:
        data = [10.0, 20.0, 30.0, 40.0]
        assert percentile(data, 50) == 25.0
        assert percentile(data, 0) == 10.0
        assert percentile(data, 100) == 40.0

    def test_percentile_single_sample(self) -> None:
        assert percentile([42.0], 95) == 42.0

    def test_percentile_unsorted_input(self) -> None:
        assert percentile([30.0, 10.0, 20.0], 50) == 20.0

    def test_percentile_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            percentile([], 50)

    def test_percentile_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            percentile([1.0], 150)

    def test_summarize(self) -> None:
        stats = summarize([100.0, 200.0, 300.0])
        assert stats == LatencyStats(n=3, p50=200.0, p95=290.0, mean=200.0)

    def test_summarize_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            summarize([])

    def test_format_row_aligned(self) -> None:
        row = LatencyStats(n=20, p50=123.4, p95=456.7, mean=200.0).format_row("stt")
        assert row.startswith("stt")
        assert "123" in row and "457" in row  # rounded to whole ms


class TestStageMapping:
    def test_known_services(self) -> None:
        assert stage_for_processor("OpenAISTTService#0") == "stt"
        assert stage_for_processor("AnthropicLLMService#0") == "llm"
        assert stage_for_processor("CartesiaTTSService#0") == "tts"

    def test_unknown_processor(self) -> None:
        assert stage_for_processor("HableYaTurnObserver#0") is None


def _pushed(frame: object) -> FramePushed:
    return FramePushed(
        source=MagicMock(),
        destination=MagicMock(),
        frame=frame,  # type: ignore[arg-type]
        direction=MagicMock(),
        timestamp=0,
    )


def _metrics_frame(processor: str, ttfb_s: float) -> MetricsFrame:
    return MetricsFrame(data=[TTFBMetricsData(processor=processor, value=ttfb_s)])


class TestObserver:
    async def test_captures_each_stage(self) -> None:
        obs = PerStageLatencyObserver()
        await obs.on_push_frame(_pushed(_metrics_frame("OpenAISTTService#0", 0.12)))
        await obs.on_push_frame(_pushed(_metrics_frame("AnthropicLLMService#0", 0.5)))
        await obs.on_push_frame(_pushed(_metrics_frame("CartesiaTTSService#0", 0.2)))
        assert list(obs.records) == [("stt", 120), ("llm", 500), ("tts", 200)]

    async def test_dedups_same_frame(self) -> None:
        obs = PerStageLatencyObserver()
        frame = _metrics_frame("OpenAISTTService#0", 0.1)
        # Same frame observed at multiple downstream hops → recorded once.
        await obs.on_push_frame(_pushed(frame))
        await obs.on_push_frame(_pushed(frame))
        await obs.on_push_frame(_pushed(frame))
        assert list(obs.records) == [("stt", 100)]

    async def test_ignores_non_metrics_frame(self) -> None:
        obs = PerStageLatencyObserver()
        await obs.on_push_frame(_pushed(TextFrame(text="hola")))
        assert list(obs.records) == []

    async def test_ignores_non_ttfb_metric(self) -> None:
        obs = PerStageLatencyObserver()
        frame = MetricsFrame(
            data=[ProcessingMetricsData(processor="OpenAISTTService#0", value=0.1)]
        )
        await obs.on_push_frame(_pushed(frame))
        assert list(obs.records) == []
