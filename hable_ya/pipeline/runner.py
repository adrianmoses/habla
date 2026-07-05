"""Pipecat pipeline composition for a single voice session.

One WS connection → one `PipelineTask` built by `build_pipeline_task()`.
Services (STT/LLM/TTS) are injected from the module-level shared pool in
`hable_ya.pipeline.services`; the per-app observation sink is injected from
`app.state`. Per-session state (transport, LLM context, aggregators, custom
processors) is built fresh inside the call.
"""

from __future__ import annotations

import logging

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
    LocalSmartTurnAnalyzerV3,
)
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.observers.base_observer import BaseObserver
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from hable_ya.config import Settings
from hable_ya.learner.ingest import TurnIngestService
from hable_ya.pipeline.processors.tool_handler import HableYaToolHandler
from hable_ya.pipeline.processors.turn_observer import HableYaTurnObserver
from hable_ya.pipeline.services import Services
from hable_ya.runtime.observations import TurnObservationSink

latency_logger = logging.getLogger("hable_ya.latency")


def default_learner(settings: Settings) -> dict[str, object]:
    """Static learner dict used until the learner model (#029) lands."""
    return {"band": settings.default_learner_band, "learner_id": "placeholder"}


def build_pipeline(
    services: Services,
    transport: FastAPIWebsocketTransport,
    context: LLMContext,
    settings: Settings,
    *,
    sink: TurnObservationSink,
    session_id: str,
    ingest: TurnIngestService | None = None,
) -> Pipeline:
    """Assemble the voice pipeline.

    Order is load-bearing: the tool handler sits immediately before TTS so
    `log_turn(...)` syntax never reaches speech synthesis.
    """
    smart_turn = LocalSmartTurnAnalyzerV3(
        params=SmartTurnParams(stop_secs=settings.smart_turn_stop_secs)
    )
    user_params = LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(
            stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=smart_turn)]
        ),
        vad_analyzer=SileroVADAnalyzer(
            sample_rate=settings.audio_sample_rate,
            params=VADParams(stop_secs=settings.vad_stop_secs),
        ),
    )
    aggregators = LLMContextAggregatorPair(context, user_params=user_params)

    turn_observer = HableYaTurnObserver()
    tool_handler = HableYaToolHandler(sink, session_id, ingest=ingest)

    return Pipeline(
        [
            transport.input(),
            services.stt,
            turn_observer,
            aggregators.user(),
            services.llm,
            tool_handler,
            services.tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )


def build_pipeline_task(
    services: Services,
    transport: FastAPIWebsocketTransport,
    context: LLMContext,
    settings: Settings,
    *,
    sink: TurnObservationSink,
    session_id: str,
    ingest: TurnIngestService | None = None,
) -> PipelineTask:
    pipeline = build_pipeline(
        services,
        transport,
        context,
        settings,
        sink=sink,
        session_id=session_id,
        ingest=ingest,
    )

    observers: list[BaseObserver] | None = None
    if settings.latency_debug:
        observer = UserBotLatencyObserver()  # type: ignore[no-untyped-call]

        @observer.event_handler("on_latency_measured")  # type: ignore[untyped-decorator]
        async def _log_latency(_obs: UserBotLatencyObserver, latency_s: float) -> None:
            latency_logger.info("end_to_end_ms=%d", int(latency_s * 1000))

        observers = [observer]

    return PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            audio_in_sample_rate=settings.audio_sample_rate,
            audio_out_sample_rate=settings.audio_sample_rate,
        ),
        observers=observers,
        idle_timeout_secs=None,
    )
