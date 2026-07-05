"""Smoke test (spec 007) — validate cloud STT + TTS against the live APIs.

Throwaway harness, the analog of spec 001's spike. Proves both credentials, the
model ids, and the Cartesia voice id work end to end:

  1. TTS: Cartesia synthesizes a short Spanish sentence -> non-empty audio.
  2. STT: OpenAI transcribes that audio -> non-empty transcript (a TTS->STT
     round-trip needs no bundled audio asset).

Run:  OPENAI_API_KEY, CARTESIA_API_KEY, CARTESIA_VOICE_ID in env or habla/.env.
      uv run python scripts/smoke_stt_tts.py

Exit 0 = both services returned non-empty results (green light).
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import wave

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
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.transcriptions.language import Language

STT_MODEL = "gpt-4o-transcribe"
TTS_MODEL = "sonic-3"
SAMPLE_RATE = 16000
SENTENCE = "Hola, me llamo Ana y hoy fui a la tienda."


class AudioCapture(FrameProcessor):
    def __init__(self, done: asyncio.Event) -> None:
        super().__init__()
        self.audio = bytearray()
        self._done = done

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            self.audio.extend(frame.audio)
        elif isinstance(frame, TTSStoppedFrame):
            self._done.set()
        await self.push_frame(frame, direction)


async def synth_tts(api_key: str, voice_id: str) -> bytes:
    tts = CartesiaTTSService(
        api_key=api_key,
        voice_id=voice_id,
        model=TTS_MODEL,
        sample_rate=SAMPLE_RATE,
        params=CartesiaTTSService.InputParams(language=Language.ES),
    )
    done = asyncio.Event()
    capture = AudioCapture(done)
    task = PipelineTask(Pipeline([tts, capture]))
    runner = PipelineRunner(handle_sigint=False)
    run_task = asyncio.create_task(runner.run(task))

    await task.queue_frame(TTSSpeakFrame(SENTENCE))
    try:
        await asyncio.wait_for(done.wait(), timeout=30)
    except TimeoutError:
        pass
    await asyncio.sleep(0.5)
    await task.queue_frame(EndFrame())
    try:
        await asyncio.wait_for(run_task, timeout=10)
    except TimeoutError:
        run_task.cancel()
    return bytes(capture.audio)


async def transcribe(api_key: str, audio: bytes) -> str:
    stt = OpenAISTTService(
        api_key=api_key,
        model=STT_MODEL,
        language=Language.ES,
        sample_rate=SAMPLE_RATE,
    )
    # In the pipeline, the StartFrame sets the working sample rate; driving
    # run_stt() standalone here, promote the constructor value ourselves
    # (otherwise it stays 0 and the transcription is empty).
    stt._sample_rate = SAMPLE_RATE  # noqa: SLF001
    # run_stt()/_transcribe() expect WAV bytes (the segmented STT wraps the
    # buffered PCM before calling it); do the same wrap here.
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio)

    parts: list[str] = []
    async for frame in stt.run_stt(wav_buf.getvalue()):
        if isinstance(frame, ErrorFrame):
            print(f"  STT ErrorFrame: {frame.error}")
            continue
        text = getattr(frame, "text", None)
        if text:
            parts.append(text)
    return " ".join(parts).strip()


async def main() -> int:
    load_dotenv()
    missing = [
        k
        for k in ("OPENAI_API_KEY", "CARTESIA_API_KEY", "CARTESIA_VOICE_ID")
        if not os.getenv(k)
    ]
    if missing:
        print(f"FAIL: missing env/.env: {', '.join(missing)}")
        return 2

    print(f"Synthesizing (Cartesia {TTS_MODEL}): {SENTENCE!r}")
    audio = await synth_tts(
        os.environ["CARTESIA_API_KEY"], os.environ["CARTESIA_VOICE_ID"]
    )
    print(f"  -> {len(audio)} bytes of PCM")

    print(f"Transcribing (OpenAI {STT_MODEL}) ...")
    transcript = await transcribe(os.environ["OPENAI_API_KEY"], audio)
    print(f"  -> {transcript!r}")

    ok = len(audio) > 0 and bool(transcript)
    print(f"\n{'PASS — cloud STT + TTS both live' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
