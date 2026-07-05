"""Manual end-to-end test harness for the /ws/session voice pipeline.

Reads a 16 kHz mono WAV, streams PCM frames over the WebSocket, writes the
response audio back to a WAV file. Run against a live `uvicorn api.main:app`
with llama.cpp up. Intended for human validation — not part of the pytest
suite.

Usage:
    python scripts/voice_client.py input.wav output.wav [--url ws://host:port/ws/session]
"""

from __future__ import annotations

import argparse
import asyncio
import wave
from pathlib import Path

import websockets

DEFAULT_URL = "ws://localhost:8000/ws/session"
SAMPLE_RATE = 16000
CHUNK_MS = 20
CHUNK_BYTES = SAMPLE_RATE * 2 * CHUNK_MS // 1000  # 16-bit mono


def _read_wav_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (
            w.getnchannels() != 1
            or w.getsampwidth() != 2
            or w.getframerate() != SAMPLE_RATE
        ):
            raise SystemExit(
                f"input WAV must be mono/16-bit/{SAMPLE_RATE}Hz; "
                f"got {w.getnchannels()}ch, "
                f"{w.getsampwidth() * 8}bit, {w.getframerate()}Hz"
            )
        return w.readframes(w.getnframes())


def _write_wav_pcm(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


async def _stream(
    url: str, input_wav: Path, output_wav: Path, listen_secs: float
) -> None:
    pcm_in = _read_wav_pcm(input_wav)
    print(f"streaming {len(pcm_in)} bytes of PCM over {url}")

    async with websockets.connect(url) as ws:
        # Send the utterance in CHUNK_MS chunks, pacing roughly real-time.
        for i in range(0, len(pcm_in), CHUNK_BYTES):
            await ws.send(pcm_in[i : i + CHUNK_BYTES])
            await asyncio.sleep(CHUNK_MS / 1000.0)

        # Then listen for response audio frames until quiet for listen_secs.
        response: bytearray = bytearray()
        try:
            while True:
                frame = await asyncio.wait_for(ws.recv(), timeout=listen_secs)
                if isinstance(frame, bytes):
                    response.extend(frame)
        except (TimeoutError, websockets.ConnectionClosed):
            pass

    if not response:
        print("no audio received from server")
        return
    _write_wav_pcm(output_wav, bytes(response))
    print(f"wrote {len(response)} bytes of response audio to {output_wav}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_wav", type=Path)
    parser.add_argument("output_wav", type=Path)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--listen-secs",
        type=float,
        default=8.0,
        help="seconds of silence after last recv before closing",
    )
    args = parser.parse_args()

    asyncio.run(_stream(args.url, args.input_wav, args.output_wav, args.listen_secs))


if __name__ == "__main__":
    main()
