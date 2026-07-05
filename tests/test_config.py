"""Config tests for the cloud model swaps (specs 001, 007)."""

from __future__ import annotations

import pytest

from hable_ya.config import Settings


def test_llama_cpp_url_removed() -> None:
    assert not hasattr(Settings(), "llama_cpp_url")


def test_anthropic_llm_defaults() -> None:
    s = Settings()
    assert hasattr(s, "anthropic_api_key")
    assert s.llm_model_name == "claude-sonnet-4-6"
    # Room for a short spoken reply plus the native log_turn tool-call args.
    assert s.llm_max_tokens >= 512


def test_anthropic_api_key_reads_standard_env(monkeypatch) -> None:
    # The key comes from the standard ANTHROPIC_API_KEY, not the HABLE_YA_
    # prefix used by the other settings.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert Settings().anthropic_api_key == "sk-test-123"


# ---- spec 007: cloud STT + TTS -------------------------------------------


@pytest.mark.parametrize(
    "removed_field",
    [
        "whisper_model",
        "whisper_device",
        "whisper_compute_type",
        "piper_voice",
        "piper_model_dir",
    ],
)
def test_local_stt_tts_fields_removed(removed_field: str) -> None:
    assert not hasattr(Settings(), removed_field)


def test_cloud_stt_tts_defaults() -> None:
    s = Settings()
    assert hasattr(s, "openai_api_key")
    assert hasattr(s, "cartesia_api_key")
    assert hasattr(s, "cartesia_voice_id")
    assert s.stt_model == "gpt-4o-transcribe"
    assert s.cartesia_model == "sonic-3"


def test_stt_tts_keys_read_standard_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-xyz")
    monkeypatch.setenv("CARTESIA_API_KEY", "cart-xyz")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "voice-xyz")
    s = Settings()
    assert s.openai_api_key == "sk-openai-xyz"
    assert s.cartesia_api_key == "cart-xyz"
    assert s.cartesia_voice_id == "voice-xyz"


# ---- spec 009: .env loading via python-dotenv -----------------------------


def test_dotenv_populates_settings(tmp_path, monkeypatch) -> None:
    from dotenv import load_dotenv

    # config.py calls load_dotenv() at import; isolate by clearing the var,
    # then load a temp .env and confirm it reaches Settings.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-from-dotenv\n")
    load_dotenv(dotenv_path=env, override=False)
    assert Settings().openai_api_key == "sk-from-dotenv"


def test_exported_env_wins_over_dotenv(tmp_path, monkeypatch) -> None:
    from dotenv import load_dotenv

    # override=False: an already-set env var is authoritative over .env.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-exported")
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-from-dotenv\n")
    load_dotenv(dotenv_path=env, override=False)
    assert Settings().openai_api_key == "sk-exported"
