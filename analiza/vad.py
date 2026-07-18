"""VAD (spec §2B): silero speech segments — the authoritative source for pause
metrics, immune to transcription errors. Silence stats are derived in
metrics.py as pure functions over these segments.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeechSegment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def detect_speech(wav_path: Path) -> list[SpeechSegment]:
    """Run silero VAD (bundled with faster-whisper) over a 16 kHz mono WAV.

    TODO(implement): use faster_whisper.vad.get_speech_timestamps /
    VadOptions; convert sample offsets to seconds.
    """
    raise NotImplementedError
