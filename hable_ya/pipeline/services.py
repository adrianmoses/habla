"""Pipeline-wide shared services (STT, LLM, TTS).

Constructed once at process startup and reused across WebSocket sessions.
Call `load_services(settings)` from a FastAPI `lifespan` context, then call
`warmup_llm(settings)` to wait for the llama.cpp endpoint to accept requests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import AsyncOpenAI
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.piper.tts import PiperTTSService
from pipecat.services.whisper.stt import Model as WhisperModel
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from hable_ya.config import Settings

logger = logging.getLogger("hable_ya.pipeline.services")


@dataclass
class Services:
    stt: WhisperSTTService
    llm: OpenAILLMService
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

    # Gemma 4 in llama.cpp defaults to thinking mode, which splits the
    # output stream into `delta.reasoning_content` (chain-of-thought) and
    # `delta.content`. Pipecat's OpenAILLMService only forwards `content`,
    # so with thinking enabled the Spanish reply never reaches our handler
    # or TTS. Disable via chat_template_kwargs so all output lands in
    # `content`.
    llm = OpenAILLMService(
        model=settings.llm_model_name,
        base_url=f"{settings.llama_cpp_url.rstrip('/')}/v1",
        api_key="not-needed",
        retry_timeout_secs=30.0,
        retry_on_timeout=True,
        params=OpenAILLMService.InputParams(
            temperature=0.7,
            top_p=0.9,
            max_completion_tokens=settings.llm_max_tokens,
            extra={
                "extra_body": {
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            },
        ),
    )
    logger.info("  LLM service ready (%s)", settings.llama_cpp_url)

    tts = PiperTTSService(
        voice_id=settings.piper_voice,
        download_dir=settings.piper_model_dir,
        sample_rate=settings.audio_sample_rate,
    )
    logger.info("  Piper TTS ready (%s)", settings.piper_voice)

    return Services(stt=stt, llm=llm, tts=tts)


async def warmup_llm(
    settings: Settings,
    *,
    max_retries: int = 10,
    retry_delay_s: float = 3.0,
) -> None:
    """Ping the llama.cpp endpoint until it accepts a 1-token completion."""
    client = AsyncOpenAI(
        base_url=f"{settings.llama_cpp_url.rstrip('/')}/v1",
        api_key="not-needed",
    )
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_fixed(retry_delay_s),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.INFO),
        reraise=True,
    ):
        with attempt:
            await client.chat.completions.create(
                model=settings.llm_model_name,
                messages=[{"role": "user", "content": "Hola"}],
                max_tokens=1,
            )
    logger.info("LLM warm")
