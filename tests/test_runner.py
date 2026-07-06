"""Structural tests for pipeline composition.

Live services require CUDA, model downloads, and a running llama.cpp — none of
which are available in automated tests. We substitute lightweight
FrameProcessor stand-ins for STT/LLM/TTS/transport and assert on the processor
order `build_pipeline()` produces. Ordering regressions would otherwise only be
catchable by manual end-to-end runs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameProcessor

from hable_ya.config import Settings
from hable_ya.pipeline.processors.latency_metrics import PerStageLatencyObserver
from hable_ya.pipeline.processors.log_turn_observer import LogTurnEmissionObserver
from hable_ya.pipeline.processors.turn_observer import HableYaTurnObserver
from hable_ya.pipeline.runner import build_observers, build_pipeline
from hable_ya.pipeline.services import Services
from hable_ya.runtime.observations import TurnObservationSink


class _StubProcessor(FrameProcessor):
    """Minimal FrameProcessor stand-in with a recognizable name."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._stub_name = name

    def __repr__(self) -> str:
        return f"<stub:{self._stub_name}>"


@pytest.fixture
def fake_services() -> Services:
    # Services' fields are typed as concrete Pipecat service classes; stubbing
    # them in tests trips mypy. FrameProcessor is the only contract the runner
    # actually needs, so the ignore is correct at the boundary.
    return Services(
        stt=_StubProcessor("stt"),  # type: ignore[arg-type]
        llm=_StubProcessor("llm"),  # type: ignore[arg-type]
        tts=_StubProcessor("tts"),  # type: ignore[arg-type]
    )


@pytest.fixture
def fake_transport() -> MagicMock:
    transport = MagicMock()
    transport.input.return_value = _StubProcessor("transport.input")
    transport.output.return_value = _StubProcessor("transport.output")
    return transport


def _sink(tmp_path: Path) -> TurnObservationSink:
    return TurnObservationSink(tmp_path / "turns.jsonl", ring_size=10)


def test_build_pipeline_returns_pipeline(
    fake_services: Services, fake_transport: MagicMock, tmp_path: Path
) -> None:
    context = LLMContext(messages=[{"role": "system", "content": "s"}])
    pipeline = build_pipeline(
        fake_services,
        fake_transport,
        context,
        Settings(),
        sink=_sink(tmp_path),
    )
    assert isinstance(pipeline, Pipeline)


def test_pipeline_processor_order(
    fake_services: Services, fake_transport: MagicMock, tmp_path: Path
) -> None:
    """The documented topology is:

        transport.input → stt → turn_observer → aggregators.user →
        llm → emission_observer → tts → transport.output → aggregators.assistant

    The log_turn emission observer MUST come after the LLM (so it sees the
    response frames) and before the TTS.
    """
    context = LLMContext(messages=[{"role": "system", "content": "s"}])
    pipeline = build_pipeline(
        fake_services,
        fake_transport,
        context,
        Settings(),
        sink=_sink(tmp_path),
    )

    processors = list(pipeline.processors)

    # Names we can recognize
    from collections.abc import Callable

    def idx_of(predicate: Callable[[FrameProcessor], bool]) -> int:
        for i, p in enumerate(processors):
            if predicate(p):
                return i
        raise AssertionError(f"no processor matched {predicate}")

    stt_idx = idx_of(lambda p: p is fake_services.stt)
    llm_idx = idx_of(lambda p: p is fake_services.llm)
    tts_idx = idx_of(lambda p: p is fake_services.tts)
    emit_idx = idx_of(lambda p: isinstance(p, LogTurnEmissionObserver))
    obs_idx = idx_of(lambda p: isinstance(p, HableYaTurnObserver))

    assert stt_idx < obs_idx < llm_idx, "turn observer must sit between STT and LLM"
    assert llm_idx < emit_idx < tts_idx, (
        "emission observer must sit between LLM and TTS"
    )


def test_custom_processors_are_fresh_per_pipeline(
    fake_services: Services, fake_transport: MagicMock, tmp_path: Path
) -> None:
    """Two pipelines built in the same process must not share per-session state."""
    context = LLMContext(messages=[{"role": "system", "content": "s"}])
    p1 = build_pipeline(
        fake_services,
        fake_transport,
        context,
        Settings(),
        sink=_sink(tmp_path),
    )
    p2 = build_pipeline(
        fake_services,
        fake_transport,
        context,
        Settings(),
        sink=_sink(tmp_path),
    )

    obs_1 = [p for p in p1.processors if isinstance(p, LogTurnEmissionObserver)]
    obs_2 = [p for p in p2.processors if isinstance(p, LogTurnEmissionObserver)]

    assert obs_1 and obs_2
    assert obs_1[0] is not obs_2[0]


def test_build_observers_off_by_default() -> None:
    """No observers unless latency_debug is set (the production default)."""
    assert build_observers(Settings()) is None


def test_build_observers_includes_per_stage_when_debug() -> None:
    """latency_debug attaches both the end-to-end and per-stage observers (#013)."""
    observers = build_observers(Settings(latency_debug=True))
    assert observers is not None
    assert any(isinstance(o, PerStageLatencyObserver) for o in observers)
    assert any(isinstance(o, UserBotLatencyObserver) for o in observers)
