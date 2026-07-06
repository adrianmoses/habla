"""Generate a test WAV for `scripts/voice_client.py`.

`voice_client.py` needs a 16 kHz / mono / 16-bit PCM WAV and the repo ships
none. This synthesizes a short Spanish utterance via Cartesia (the same service
the runtime uses) and writes it in exactly that format — a no-mic on-ramp for
the voice-session live checks (spec #016).

Run:  CARTESIA_API_KEY + CARTESIA_VOICE_ID in env or habla/.env.
      uv run python scripts/make_test_wav.py [out.wav] [--text "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from pathlib import Path

from dotenv import load_dotenv
from pipecat.frames.frames import (
    EndFrame,
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
from pipecat.transcriptions.language import Language

from hable_ya.config import Settings

DEFAULT_TEXT = "Hola, me llamo Ana y hoy fui a la tienda."
SAMPLE_RATE = 16000


class _Capture(FrameProcessor):
    """Collect TTS audio frames (Cartesia pushes them downstream, not via a
    return value — see scripts/smoke_stt_tts.py)."""

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


async def synth(settings: Settings, text: str) -> bytes:
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        voice_id=settings.cartesia_voice_id,
        model=settings.cartesia_model,
        sample_rate=SAMPLE_RATE,
        params=CartesiaTTSService.InputParams(language=Language.ES),
    )
    done = asyncio.Event()
    capture = _Capture(done)
    task = PipelineTask(Pipeline([tts, capture]))
    runner = PipelineRunner(handle_sigint=False)
    run = asyncio.create_task(runner.run(task))

    await task.queue_frame(TTSSpeakFrame(text))
    try:
        await asyncio.wait_for(done.wait(), timeout=30)
    except TimeoutError:
        pass
    await task.queue_frame(EndFrame())
    try:
        await asyncio.wait_for(run, timeout=10)
    except TimeoutError:
        run.cancel()
    return bytes(capture.audio)


def _write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize a test WAV via Cartesia")
    parser.add_argument("output", nargs="?", type=Path, default=Path("in.wav"))
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Spanish text to speak")
    parser.add_argument(
        "--trailing-silence-secs",
        type=float,
        default=1.0,
        help="silence appended after the utterance so the server's VAD can "
        "endpoint the turn when this WAV is streamed (default 1.0)",
    )
    args = parser.parse_args()

    load_dotenv()
    settings = Settings()
    missing = [
        name
        for name, val in (
            ("CARTESIA_API_KEY", settings.cartesia_api_key),
            ("CARTESIA_VOICE_ID", settings.cartesia_voice_id),
        )
        if not val
    ]
    if missing:
        print(f"FAIL: missing env/.env: {', '.join(missing)}")
        return 2

    print(f"Synthesizing (Cartesia {settings.cartesia_model}): {args.text!r}")
    pcm = await synth(settings, args.text)
    if not pcm:
        print("FAIL: no audio produced")
        return 1
    # Pad with trailing silence so the runtime VAD endpoints the turn (2 bytes
    # per 16-bit sample).
    pcm += bytes(int(args.trailing_silence_secs * SAMPLE_RATE) * 2)
    _write_wav(args.output, pcm)
    secs = len(pcm) / 2 / SAMPLE_RATE
    print(f"Wrote {args.output} ({len(pcm)} bytes, ~{secs:.1f}s, 16kHz/mono/16-bit)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
