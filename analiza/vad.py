"""VAD (spec §2B): silero speech segments — the authoritative source for pause
metrics, immune to transcription errors. Silence stats are derived in
metrics.py as pure functions over these segments.
"""

from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class SpeechSegment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def detect_speech(wav_path: Path) -> list[SpeechSegment]:
    """Run silero VAD (bundled with faster-whisper) over a 16 kHz mono WAV."""
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    audio = decode_audio(str(wav_path), sampling_rate=SAMPLE_RATE)
    timestamps = get_speech_timestamps(audio, VadOptions())
    return [
        SpeechSegment(start=t["start"] / SAMPLE_RATE, end=t["end"] / SAMPLE_RATE)
        for t in timestamps
    ]
