"""Pipeline-wide shared services (STT, LLM, TTS).

Constructed once at process startup and reused across WebSocket sessions.
Call `load_services(settings)` from a FastAPI `lifespan` context, then call
`warmup_llm(settings)` to confirm the Anthropic API accepts a request before
flipping the app to ready.

The LLM is Claude via the Anthropic API (spec 001). STT (faster-whisper) and
TTS (Piper) remain on-device in this slice; roadmap #007/#008 move them to
managed APIs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.piper.tts import PiperTTSService
from pipecat.services.whisper.stt import Model as WhisperModel
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language

from hable_ya.config import Settings

logger = logging.getLogger("hable_ya.pipeline.services")


@dataclass
class Services:
    stt: WhisperSTTService
    llm: AnthropicLLMService
    tts: PiperTTSService


def load_services(settings: Settings) -> Services:
    logger.info("Loading Pipecat services")
    stt = WhisperSTTService(
        model=WhisperModel[settings.whisper_model.upper()],
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        no_speech_prob=0.6,
        language=Language.ES,
    )
    logger.info(
        "  Whisper STT ready (%s, %s)",
        settings.whisper_model,
        settings.whisper_device,
    )

    # Thinking is disabled: a real-time voice turn must not stall on a
    # reasoning pass. This is the Claude analog of the on-device Gemma
    # `enable_thinking=false` chat-template hack. `HABLE_YA_TOOLS_SCHEMA` is
    # attached per session on the LLMContext (see api/routes/session.py), and
    # the `log_turn` handler is registered there too, so tools live with the
    # per-session state rather than on this shared service.
    llm = AnthropicLLMService(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model_name,
        params=AnthropicLLMService.InputParams(
            temperature=0.7,
            max_tokens=settings.llm_max_tokens,
            thinking=AnthropicLLMService.ThinkingConfig(type="disabled"),
        ),
    )
    logger.info("  LLM service ready (%s)", settings.llm_model_name)

    tts = PiperTTSService(
        voice_id=settings.piper_voice,
        download_dir=settings.piper_model_dir,
        sample_rate=settings.audio_sample_rate,
    )
    logger.info("  Piper TTS ready (%s)", settings.piper_voice)

    return Services(stt=stt, llm=llm, tts=tts)


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
