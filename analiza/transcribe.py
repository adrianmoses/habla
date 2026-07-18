"""Transcription (spec §2C): faster-whisper wrapper + raw JSON persistence.

Fixed decode settings: word_timestamps=True, language forced (default "es"),
condition_on_previous_text=False (reduces error-correction smoothing),
temperature=0. Raw JSON is persisted so 90 days of audio can be reprocessed
with better logic without re-transcription.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TranscriptionError(Exception):
    """Whisper failed to produce a transcript (exit code 1)."""


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    prob: float


@dataclass(frozen=True)
class Transcription:
    text: str
    words: list[Word]
    language: str
    # Full segments+words+probabilities structure, persisted verbatim.
    raw: dict[str, Any]


def transcribe(
    wav_path: Path, model: str = "small", language: str = "es"
) -> Transcription:
    """Run faster-whisper over the prepared WAV.

    TODO(implement): WhisperModel(model, device="cuda", compute_type=...),
    model.transcribe(word_timestamps=True, language=language,
    condition_on_previous_text=False, temperature=0); flatten segment words
    into Word list and keep the raw structure for persistence.
    """
    raise NotImplementedError


def persist_raw(transcription: Transcription, dest: Path) -> None:
    """Write the raw whisper JSON alongside the other artifacts."""
    dest.write_text(json.dumps(transcription.raw, ensure_ascii=False, indent=2))
