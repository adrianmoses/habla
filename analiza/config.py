"""Config: ~/.config/analiza/config.toml, every field overridable per run via CLI."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

CONFIG_PATH = Path.home() / ".config" / "analiza" / "config.toml"


class Thresholds(BaseModel):
    """Metric thresholds. Defaults per spec §2D; all overridable in config.toml."""

    pause_s: float = 0.7  # VAD silence counts as a pause at/above this
    low_conf_prob: float = 0.5  # word prob below this joins a low_conf_span
    min_duration_s: float = 30.0  # reject shorter audio (metrics meaningless)
    warn_duration_s: float = 600.0  # warn above 10 min


class Config(BaseModel):
    vault_path: Path | None = None
    whisper_model: str = "small"
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5"
    llm_key_env: str = "ANTHROPIC_API_KEY"
    # None → use the bundled analiza.conectores_b2 list
    connector_list_path: Path | None = None
    copy_source_audio: bool = False
    thresholds: Thresholds = Field(default_factory=Thresholds)


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config.toml; a missing file yields pure defaults."""
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        return Config.model_validate(tomllib.load(f))
