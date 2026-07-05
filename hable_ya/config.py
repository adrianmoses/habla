from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Dev convenience: populate os.environ from a .env in the working directory
# before Settings is constructed. override=False so an exported var or a
# container-injected value always wins over .env. Feeds the validation_alias
# fields below (ANTHROPIC/OPENAI/CARTESIA keys) and anything reading os.environ.
load_dotenv()


class Settings(BaseSettings):
    model_config = {"env_prefix": "HABLE_YA_"}

    database_url: str = "postgresql://hable_ya:hable_ya@localhost:5433/hable_ya"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 4
    db_pool_timeout_seconds: float = 5.0

    @property
    def async_database_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # Claude via the Anthropic API (spec 001). The key is read from the
    # standard ANTHROPIC_API_KEY env var (not the HABLE_YA_ prefix), matching
    # the Anthropic SDK and the eval workstream.
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    llm_model_name: str = "claude-sonnet-4-6"
    # Room for a short spoken reply plus the native log_turn tool-call args.
    llm_max_tokens: int = 1024

    # STT via the OpenAI transcription API (spec 007). Key read from the
    # standard OPENAI_API_KEY. gpt-4o-transcribe is stronger on Spanish than
    # whisper-1 (the axis the on-device faster-whisper was weakest on).
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    stt_model: str = "gpt-4o-transcribe"

    # TTS via Cartesia (spec 007). voice_id is owner-supplied (no safe default;
    # the runtime/smoke fail fast if unset).
    cartesia_api_key: str = Field(default="", validation_alias="CARTESIA_API_KEY")
    cartesia_voice_id: str = Field(default="", validation_alias="CARTESIA_VOICE_ID")
    cartesia_model: str = "sonic-3"

    smart_turn_stop_secs: float = 4.0
    vad_stop_secs: float = 0.5

    audio_sample_rate: int = 16000

    default_learner_band: str = "A2"
    runtime_turns_path: Path = Path("runtime_turns.jsonl")
    observation_ring_size: int = 100
    dev_endpoints_enabled: bool = False
    latency_debug: bool = False

    # Learner-model (spec 029) tunables.
    profile_window_turns: int = 20  # rolling window for L1_reliance / fluency
    profile_top_errors: int = 3  # top-N error categories surfaced in prompt
    profile_top_vocab: int = 5  # top-N vocab lemmas surfaced in prompt
    theme_cooldown: int = 3  # recent themes excluded from selection

    # Leveling (spec 049) tunables.
    leveling_window_sessions: int = 3  # last-N sessions of turns the rolling
    # mean reads. Independent of profile_window_turns (which is per-turn);
    # session-keyed so a single chatty session can't outweigh several quiet ones.
    leveling_promote_consecutive: int = 3  # K-of-K promote-target sessions
    leveling_demote_consecutive: int = 4  # K-of-K demote-target sessions
    placement_min_valid_turns: int = 3  # below this, placement abstains and
    # the learner re-enters the diagnostic on the next session.


settings = Settings()
