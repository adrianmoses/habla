"""Config tests for the cloud LLM swap (spec 001)."""

from __future__ import annotations

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
