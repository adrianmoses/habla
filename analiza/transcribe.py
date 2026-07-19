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
    """Run faster-whisper over the prepared WAV."""
    from faster_whisper import WhisperModel

    def _run(device: str, compute_type: str):  # type: ignore[no-untyped-def]
        whisper = WhisperModel(model, device=device, compute_type=compute_type)
        segments_iter, info = whisper.transcribe(
            str(wav_path),
            word_timestamps=True,
            language=language,
            condition_on_previous_text=False,
            temperature=0,
        )
        # Materialize here: transcription is lazy, and device errors (missing
        # CUDA runtime libs) only surface on iteration.
        return list(segments_iter), info

    try:
        try:
            segments_iter, info = _run("auto", "default")
        except Exception as e:
            # A GPU may be present without the CUDA runtime libs installed
            # (libcublas/libcudnn) — fall back to CPU rather than failing.
            if not any(s in str(e) for s in ("cublas", "cudnn", "CUDA")):
                raise
            segments_iter, info = _run("cpu", "int8")
        raw_segments: list[dict[str, Any]] = []
        words: list[Word] = []
        texts: list[str] = []
        for seg in segments_iter:
            seg_words = [
                {
                    "word": w.word,
                    "start": w.start,
                    "end": w.end,
                    "probability": w.probability,
                }
                for w in (seg.words or [])
            ]
            raw_segments.append(
                {
                    "id": seg.id,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                    "avg_logprob": seg.avg_logprob,
                    "no_speech_prob": seg.no_speech_prob,
                    "words": seg_words,
                }
            )
            texts.append(seg.text.strip())
            words.extend(
                Word(text=w["word"].strip(), start=w["start"], end=w["end"],
                     prob=w["probability"])
                for w in seg_words
            )
    except Exception as e:
        raise TranscriptionError(str(e)) from e

    text = " ".join(t for t in texts if t)
    if not text:
        raise TranscriptionError("whisper produced an empty transcript")
    return Transcription(
        text=text,
        words=words,
        language=info.language,
        raw={
            "model": model,
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
            "segments": raw_segments,
        },
    )


def persist_raw(transcription: Transcription, dest: Path) -> None:
    """Write the raw whisper JSON alongside the other artifacts."""
    dest.write_text(json.dumps(transcription.raw, ensure_ascii=False, indent=2))
