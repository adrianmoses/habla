"""Preprocess (spec §2A): ffmpeg → 16 kHz mono WAV, duration checks."""

import subprocess
from dataclasses import dataclass
from pathlib import Path


class AudioUnreadableError(Exception):
    """Source audio missing or ffmpeg/ffprobe could not decode it (exit code 2)."""


@dataclass(frozen=True)
class PreparedAudio:
    wav_path: Path  # 16 kHz mono WAV, whisper's native format
    duration_s: float
    source_path: Path


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise AudioUnreadableError(f"ffprobe failed on {path}: {result.stderr.strip()}")
    return float(result.stdout.strip())


def preprocess(source: Path, workdir: Path) -> PreparedAudio:
    """Convert to 16 kHz mono WAV in workdir and record total duration.

    Duration warnings (<30 s reject, >10 min warn) are the CLI's job — this
    function only converts and measures.
    """
    if not source.exists():
        raise AudioUnreadableError(f"no such file: {source}")
    wav_path = workdir / f"{source.stem}.16k.wav"
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(source),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AudioUnreadableError(
            f"ffmpeg failed on {source}: {result.stderr.strip()}"
        )
    return PreparedAudio(
        wav_path=wav_path,
        duration_s=probe_duration(wav_path),
        source_path=source,
    )
