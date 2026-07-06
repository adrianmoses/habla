"""Cloud round-trip latency benchmark (spec #013).

Measures the per-stage network latency the cloud fork added over on-device
hable-ya, so the turn-taking defaults (`smart_turn_stop_secs`, `vad_stop_secs`)
can be re-tuned against real numbers. Replaces the on-device
`benchmark_latency.py` deleted in #011.

For a fixed corpus of short Spanish learner utterances, over N iterations, it
times each stage independently and reports p50/p95/mean (ms):

  - STT   : OpenAI transcription — probe audio -> transcript
  - LLM   : Claude time-to-first-token — transcript -> first streamed token
  - TTS   : Cartesia time-to-first-byte — reply text -> first audio frame

The three services are built via `load_services(settings)`, so this inherits
the exact runtime config (model ids, voice, sample rate, thinking disabled).
LLM TTFT is measured with the raw Anthropic streaming SDK against the same
model — `AnthropicLLMService` is a pipeline processor, awkward to drive
standalone, but wraps the identical endpoint.

Run:  ANTHROPIC_API_KEY, OPENAI_API_KEY, CARTESIA_API_KEY, CARTESIA_VOICE_ID in
      env or habla/.env.
      uv run python scripts/benchmark_latency.py [--iterations 20] [--output f.json]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
import wave
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from pipecat.frames.frames import (
    EndFrame,
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from hable_ya.config import Settings
from hable_ya.pipeline.services import Services, load_services
from hable_ya.runtime.latency import STATS_HEADER, LatencyStats, summarize

# Short, representative learner utterances (A2-ish, the kind the STT/LLM path
# actually sees). Kept fixed so runs are comparable across invocations.
CORPUS: tuple[str, ...] = (
    "Hola, me llamo Ana y hoy fui a la tienda.",
    "Ayer yo comí una manzana muy grande.",
    "¿Puedes ayudarme con mi tarea de español?",
    "No entiendo esta palabra, ¿qué significa?",
)


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


class _TTSCapture(FrameProcessor):
    """Records first-audio time and accumulates PCM for one synthesis request.

    The streaming Cartesia service doesn't return audio from `run_tts()` — it
    pushes `TTSAudioRawFrame`s downstream via its websocket receive task — so we
    capture them here, the same pattern as `scripts/smoke_stt_tts.py`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.reset()

    def reset(self) -> None:
        self.audio = bytearray()
        self.first_audio_at: float | None = None
        self.first = asyncio.Event()
        self.stopped = asyncio.Event()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            if self.first_audio_at is None:
                self.first_audio_at = time.perf_counter()
                self.first.set()
            self.audio.extend(frame.audio)
        elif isinstance(frame, TTSStoppedFrame):
            self.stopped.set()
        await self.push_frame(frame, direction)


class _TTSDriver:
    """A persistent TTS pipeline so the websocket connects once (warm TTFB)."""

    def __init__(self, services: Services, sample_rate: int) -> None:
        services.tts._sample_rate = sample_rate  # noqa: SLF001
        self.capture = _TTSCapture()
        self.task = PipelineTask(
            Pipeline([services.tts, self.capture]),
            params=PipelineParams(audio_out_sample_rate=sample_rate),
        )
        self.runner = PipelineRunner(handle_sigint=False)
        self._run: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._run = asyncio.create_task(self.runner.run(self.task))

    async def synth(self, text: str) -> tuple[bytes, float]:
        """Synthesize `text`; return (PCM audio, time-to-first-byte ms)."""
        self.capture.reset()
        t0 = time.perf_counter()
        await self.task.queue_frame(TTSSpeakFrame(text))
        await asyncio.wait_for(self.capture.first.wait(), timeout=30)
        await asyncio.wait_for(self.capture.stopped.wait(), timeout=30)
        assert self.capture.first_audio_at is not None
        return bytes(self.capture.audio), (self.capture.first_audio_at - t0) * 1000.0

    async def stop(self) -> None:
        await self.task.queue_frame(EndFrame())
        if self._run is not None:
            try:
                await asyncio.wait_for(self._run, timeout=10)
            except TimeoutError:
                self._run.cancel()


async def _time_stt(services: Services, wav_bytes: bytes, sample_rate: int) -> float:
    services.stt._sample_rate = sample_rate  # noqa: SLF001
    t0 = time.perf_counter()
    async for frame in services.stt.run_stt(wav_bytes):
        if isinstance(frame, ErrorFrame):
            raise RuntimeError(f"STT error: {frame.error}")
        if getattr(frame, "text", None):
            return (time.perf_counter() - t0) * 1000.0
    raise RuntimeError("STT produced no transcript")


async def _time_llm_ttft(
    client: AsyncAnthropic, settings: Settings, prompt: str
) -> float:
    t0 = time.perf_counter()
    async with client.messages.stream(
        model=settings.llm_model_name,
        max_tokens=settings.llm_max_tokens,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for _text in stream.text_stream:
            return (time.perf_counter() - t0) * 1000.0
    raise RuntimeError("LLM produced no tokens")


async def run_benchmark(settings: Settings, iterations: int) -> dict[str, LatencyStats]:
    services = load_services(settings)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    rate = settings.audio_sample_rate

    tts = _TTSDriver(services, rate)
    await tts.start()
    try:
        # Synthesize probe audio for STT once (also warms the TTS websocket, so
        # the measured TTS TTFB below excludes connection setup).
        print(f"Synthesizing {len(CORPUS)} probe utterances (Cartesia) ...")
        probes = [_pcm_to_wav((await tts.synth(text))[0], rate) for text in CORPUS]

        stt_ms: list[float] = []
        llm_ms: list[float] = []
        tts_ms: list[float] = []

        print(f"Running {iterations} iterations across {len(CORPUS)} utterances ...")
        for i in range(iterations):
            text = CORPUS[i % len(CORPUS)]
            wav_bytes = probes[i % len(CORPUS)]
            stt_ms.append(await _time_stt(services, wav_bytes, rate))
            llm_ms.append(await _time_llm_ttft(client, settings, text))
            tts_ms.append((await tts.synth(text))[1])
            print(f"  [{i + 1}/{iterations}] done", end="\r", flush=True)
        print()
    finally:
        await tts.stop()

    return {
        "stt": summarize(stt_ms),
        "llm": summarize(llm_ms),
        "tts": summarize(tts_ms),
    }


def _print_report(stats: dict[str, LatencyStats]) -> None:
    print("\n" + STATS_HEADER)
    for stage in ("stt", "llm", "tts"):
        print(stats[stage].format_row(stage))
    end_to_end = sum(stats[s].p50 for s in ("stt", "llm", "tts"))
    end_to_end_p95 = sum(stats[s].p95 for s in ("stt", "llm", "tts"))
    print("-" * len(STATS_HEADER))
    print(
        f"{'end_to_end':<12} {'':>4} "
        f"{end_to_end:>8.0f} {end_to_end_p95:>8.0f} {'':>8}"
    )
    print(
        "\n(end_to_end = summed per-stage p50/p95; excludes endpointing delay "
        "vad_stop_secs / smart_turn_stop_secs)"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud per-stage latency benchmark")
    parser.add_argument("--iterations", type=int, default=20, help="samples per stage")
    parser.add_argument("--output", type=Path, default=None, help="write raw JSON here")
    args = parser.parse_args()

    load_dotenv()
    settings = Settings()
    missing = [
        name
        for name, val in (
            ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
            ("OPENAI_API_KEY", settings.openai_api_key),
            ("CARTESIA_API_KEY", settings.cartesia_api_key),
            ("CARTESIA_VOICE_ID", settings.cartesia_voice_id),
        )
        if not val
    ]
    if missing:
        print(f"FAIL: missing env/.env: {', '.join(missing)}")
        return 2

    stats = await run_benchmark(settings, args.iterations)
    _print_report(stats)

    if args.output:
        payload = {
            "model": settings.llm_model_name,
            "stt_model": settings.stt_model,
            "tts_model": settings.cartesia_model,
            "iterations": args.iterations,
            "stages": {k: vars(v) for k, v in stats.items()},
        }
        args.output.write_text(json.dumps(payload, indent=2))
        print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
