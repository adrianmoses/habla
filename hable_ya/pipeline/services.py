"""Pipecat services (STT, LLM, TTS).

Two entry points (spec #016):
- `load_services(settings)` — build the shared instances once in the FastAPI
  `lifespan`, used only for startup warmup + health probes.
- `build_session_services(settings)` — build a *fresh* set per WebSocket session.
  Each session owns its LLM/STT/TTS so the per-session `log_turn` handler (bound
  via `register_function` on the LLM) and the Cartesia per-context websocket
  cannot be clobbered by a concurrent connection. Cheap: HTTP/websocket clients,
  no model load.

Call `warmup_llm(settings)` after `load_services` to confirm the Anthropic API
accepts a request before flipping the app to ready.

All three services are managed APIs: Claude (LLM, spec 001), OpenAI
transcription (STT) and Cartesia (TTS) (spec 007). Only the small Silero VAD +
SmartTurn ONNX models remain local (CPU), so the model path needs no GPU.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.transcriptions.language import Language

from hable_ya.config import Settings

logger = logging.getLogger("hable_ya.pipeline.services")


@dataclass
class Services:
    stt: OpenAISTTService
    llm: AnthropicLLMService
    tts: CartesiaTTSService


def build_session_services(settings: Settings) -> Services:
    """Construct a fresh STT/LLM/TTS set. Quiet — called per session."""
    stt = OpenAISTTService(
        api_key=settings.openai_api_key,
        model=settings.stt_model,
        language=Language.ES,
    )
    # Thinking is disabled: a real-time voice turn must not stall on a
    # reasoning pass. This is the Claude analog of the on-device Gemma
    # `enable_thinking=false` chat-template hack. The `HABLE_YA_TOOLS_SCHEMA`
    # and the `log_turn` handler are attached per session (see
    # api/routes/session.py) — and, since this instance is per session, that
    # registration cannot be clobbered by a concurrent connection.
    llm = AnthropicLLMService(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model_name,
        params=AnthropicLLMService.InputParams(
            temperature=0.7,
            max_tokens=settings.llm_max_tokens,
            thinking=AnthropicLLMService.ThinkingConfig(type="disabled"),
        ),
    )
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        voice_id=settings.cartesia_voice_id,
        model=settings.cartesia_model,
        sample_rate=settings.audio_sample_rate,
        params=CartesiaTTSService.InputParams(language=Language.ES),
    )
    return Services(stt=stt, llm=llm, tts=tts)


def load_services(settings: Settings) -> Services:
    """Build the shared instances for startup warmup + health probes."""
    logger.info("Loading Pipecat services")
    services = build_session_services(settings)
    logger.info("  OpenAI STT ready (%s)", settings.stt_model)
    logger.info("  LLM service ready (%s)", settings.llm_model_name)
    logger.info(
        "  Cartesia TTS ready (%s, voice %s)",
        settings.cartesia_model,
        settings.cartesia_voice_id or "<unset>",
    )
    return services


async def warmup_llm(settings: Settings) -> None:
    """Confirm the Anthropic API accepts a 1-token request.

    A managed API has no cold-start to poll for, so this is a single
    fail-fast health check (surfacing a missing/invalid key at startup)
    rather than the retry loop the llama.cpp backend needed.
    """
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    await client.messages.create(
        model=settings.llm_model_name,
        max_tokens=1,
        messages=[{"role": "user", "content": "Hola"}],
    )
    logger.info("LLM warm (%s)", settings.llm_model_name)
