from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import transcribe_audio


def test_transcribe_sends_english_language_hint(monkeypatch, tmp_path: Path) -> None:
    audio_file = tmp_path / "recording.m4a"
    audio_file.write_bytes(b"audio")
    captured = {}

    class FakeTranscriptions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="Hello world")

    fake_client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=FakeTranscriptions())
    )
    monkeypatch.setattr(transcribe_audio, "OpenAI", lambda **kwargs: fake_client)

    result = transcribe_audio.transcribe(audio_file, "test-key", "en")

    assert result == "Hello world"
    assert captured["model"] == "gpt-transcribe"
    assert captured["language"] == "en"
    assert captured["file"].closed


def test_transcribe_omits_language_hint_for_auto(monkeypatch, tmp_path: Path) -> None:
    audio_file = tmp_path / "recording.m4a"
    audio_file.write_bytes(b"audio")
    captured = {}

    class FakeTranscriptions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="Hola")

    fake_client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=FakeTranscriptions())
    )
    monkeypatch.setattr(transcribe_audio, "OpenAI", lambda **kwargs: fake_client)

    transcribe_audio.transcribe(audio_file, "test-key", "auto")

    assert "language" not in captured


def test_validate_audio_file_rejects_unknown_format(tmp_path: Path) -> None:
    audio_file = tmp_path / "recording.txt"
    audio_file.write_text("not audio")

    with pytest.raises(ValueError, match="unsupported audio format"):
        transcribe_audio.validate_audio_file(audio_file)
