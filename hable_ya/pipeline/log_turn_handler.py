"""Native ``log_turn`` tool-call handler (spec 001).

Claude emits ``log_turn`` as a native tool call; Pipecat's
``AnthropicLLMService`` dispatches it to a handler registered via
``register_function``. :func:`make_log_turn_handler` builds that handler as a
closure over the per-session sink / session id / ingest.

The handler is fire-and-forget: it records the observation and answers the
tool call with ``run_llm=False`` so the pedagogical side-effect does not
trigger a second spoken turn. It **always** calls ``result_callback`` (even on
a dispatch error) — an unanswered ``tool_use`` block would make the next
request 400.

This replaces the pre-cloud text-parsing ``HableYaToolHandler`` FrameProcessor,
which buffered the model's TEXT stream to regex ``log_turn(...)`` out of it —
obsolete now that the call arrives as a structured native block. Counting turns
that emit *no* ``log_turn`` (the emission-rate metric) lives in
:class:`hable_ya.pipeline.processors.log_turn_observer.LogTurnEmissionObserver`;
this handler only sees turns that *did* call the tool.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pipecat.frames.frames import FunctionCallResultProperties
from pipecat.services.llm_service import FunctionCallParams

from hable_ya.learner.ingest import TurnIngestService
from hable_ya.pipeline.prompts.render import normalize_runtime_log_turn_args
from hable_ya.runtime.observations import TurnObservation, TurnObservationSink

logger = logging.getLogger("hable_ya.pipeline.log_turn_handler")

LogTurnHandler = Callable[[FunctionCallParams], Awaitable[None]]


def make_log_turn_handler(
    sink: TurnObservationSink,
    session_id: str,
    *,
    ingest: TurnIngestService | None = None,
) -> LogTurnHandler:
    """Build the per-session ``log_turn`` function handler."""

    async def handle_log_turn(params: FunctionCallParams) -> None:
        try:
            raw_args = params.arguments
            if not isinstance(raw_args, dict):
                sink.missing += 1
                logger.warning(
                    "session %s: log_turn arguments not a dict: %r",
                    session_id,
                    raw_args,
                )
                return

            normalized = normalize_runtime_log_turn_args(dict(raw_args))
            if normalized is None:
                sink.missing += 1
                logger.warning(
                    "session %s: log_turn args failed validation: %r",
                    session_id,
                    raw_args,
                )
                return

            cefr_band = normalized.get("cefr_band")
            if cefr_band is None:
                sink.band_missing += 1
                logger.warning(
                    "session %s: log_turn omitted or invalid cefr_band: raw=%r",
                    session_id,
                    raw_args.get("cefr_band"),
                )

            obs = TurnObservation.now(
                session_id=session_id,
                learner_utterance=normalized["learner_utterance"],
                errors=normalized["errors"],
                fluency_signal=normalized["fluency_signal"],
                L1_used=normalized["L1_used"],
                cefr_band=cefr_band,
            )
            await sink.append(obs)
            if ingest is not None:
                try:
                    await ingest.ingest(obs)
                except Exception:
                    sink.ingest_failed += 1
                    logger.exception(
                        "session %s: learner DB ingest failed — "
                        "observation kept in JSONL only",
                        session_id,
                    )
        finally:
            # Always answer the tool call. run_llm=False keeps this
            # fire-and-forget observation from triggering a second inference
            # (the spoken reply already streamed this turn).
            await params.result_callback(
                {"status": "logged"},
                properties=FunctionCallResultProperties(run_llm=False),
            )

    return handle_log_turn
