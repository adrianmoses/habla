"""Transcribe an audio file with OpenAI's gpt-transcribe model.

Examples:
    uv run python scripts/transcribe_audio.py recording.m4a
    uv run python scripts/transcribe_audio.py recording.m4a \
        --language es -o transcript.txt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

MODEL = "gpt-transcribe"
SUPPORTED_FORMATS = {
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe an audio file using OpenAI gpt-transcribe."
    )
    parser.add_argument("audio_file", type=Path, help="Audio file to transcribe")
    parser.add_argument(
        "-l",
        "--language",
        default="en",
        help="ISO-639-1 input language code (default: en); use 'auto' to detect it",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the transcript to this file instead of standard output",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="File containing OPENAI_API_KEY (default: .env)",
    )
    return parser.parse_args(argv)


def validate_audio_file(audio_file: Path) -> None:
    if not audio_file.is_file():
        raise ValueError(f"audio file does not exist: {audio_file}")
    if audio_file.suffix.lower() not in SUPPORTED_FORMATS:
        formats = ", ".join(sorted(SUPPORTED_FORMATS))
        raise ValueError(
            f"unsupported audio format {audio_file.suffix!r}; use: {formats}"
        )


def transcribe(audio_file: Path, api_key: str, language: str) -> str:
    request: dict[str, object] = {"model": MODEL}
    if language.lower() != "auto":
        request["language"] = language.lower()

    client = OpenAI(api_key=api_key)
    with audio_file.open("rb") as audio:
        transcription = client.audio.transcriptions.create(file=audio, **request)
    return transcription.text


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(args.env_file)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print(
            f"error: OPENAI_API_KEY is missing from the environment or {args.env_file}",
            file=sys.stderr,
        )
        return 2

    try:
        validate_audio_file(args.audio_file)
        transcript = transcribe(args.audio_file, api_key, args.language)
    except (ValueError, OSError, OpenAIError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        if args.output:
            args.output.write_text(transcript + "\n", encoding="utf-8")
            print(f"Transcript written to {args.output}", file=sys.stderr)
        else:
            print(transcript)
    except OSError as exc:
        print(f"error: could not write transcript: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
