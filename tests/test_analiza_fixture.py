"""Real-audio fixture test (spec §3): preprocess + VAD over the checked-in
recording. Skips when the analiza extra (faster-whisper) or ffmpeg is absent.
Whisper transcription is deliberately not exercised here — it would download
a ~460 MB model; the full pipeline is covered by the CLI's manual e2e runs.
"""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("faster_whisper")
if shutil.which("ffmpeg") is None:
    pytest.skip("ffmpeg not on PATH", allow_module_level=True)

from analiza import audio, metrics, vad  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "analiza" / "monologo-prueba-65s.m4a"


def test_preprocess_and_vad_on_real_recording(tmp_path: Path) -> None:
    prepared = audio.preprocess(FIXTURE, tmp_path)
    assert prepared.wav_path.exists()
    assert prepared.duration_s == pytest.approx(65.4, abs=0.5)

    segments = vad.detect_speech(prepared.wav_path)
    assert segments
    assert all(0 <= s.start < s.end <= prepared.duration_s + 0.5 for s in segments)

    speech = metrics.speech_time_s(segments)
    # Hand-checked: the recording is mostly continuous speech with a few pauses.
    assert 40.0 < speech < prepared.duration_s

    n, total, longest = metrics.pauses(segments, prepared.duration_s, 0.7)
    assert n >= 1
    assert longest < 10.0
