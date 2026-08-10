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


class ProgresoThresholds(BaseModel):
    """Progress-report gates (spec 034). Defaults are the approved proposals;
    calibration is deferred until ≥10 sessions exist, so every one is
    overridable rather than tuned against a corpus of one."""

    # Fixed first-N vs last-N (OQ4). Fixed, not first-third/last-third: a
    # proportional window silently changes meaning as history grows, so two
    # reports a month apart would not compare like with like.
    ventana_n: int = 5
    # Consecutive sessions a pattern must be *conclusively* absent from before
    # it reads as gone (OQ2). Rendered as "ausente desde hace N sesiones",
    # never as a verdict — calling a fault fixed is the learner's call.
    ausencia_n: int = 3
    # Below this, no narrative (OQ3). A confident story fitted to five
    # sessions is worse than no story.
    min_sesiones: int = 8
    # vad_transcript_gap_s / duration_s above this flags the session
    # low-confidence. A ratio rather than an absolute second count: with an
    # absolute one a 20-minute session would have to be twice as broken as a
    # 10-minute one to flag.
    vad_gap_ratio: float = 0.10


class Config(BaseModel):
    # Optional. When set, outputs use the Obsidian vault layout (nested under
    # Español/); it takes precedence over output_dir. With neither set,
    # analiza writes flat to note.DEFAULT_OUTPUT_DIR — no vault required.
    vault_path: Path | None = None
    output_dir: Path | None = None
    whisper_model: str = "small"
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5"
    llm_key_env: str = "ANTHROPIC_API_KEY"
    # None → use the bundled analiza.conectores_b2 list
    connector_list_path: Path | None = None
    copy_source_audio: bool = False
    thresholds: Thresholds = Field(default_factory=Thresholds)
    progreso: ProgresoThresholds = Field(default_factory=ProgresoThresholds)


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config.toml; a missing file yields pure defaults."""
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        return Config.model_validate(tomllib.load(f))
