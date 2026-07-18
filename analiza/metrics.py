"""Metrics (spec §2D): pure functions over VAD segments + word list. No I/O.

Everything here must stay deterministic and reproducible across 90 days —
never route a metric through the LLM. Output is a flat dict → JSON.
"""

from analiza.config import Thresholds
from analiza.connectors import ConnectorMatch
from analiza.transcribe import Word
from analiza.vad import SpeechSegment

# Filler inventory. Whisper suppresses fillers, so counts derived from this
# are a floor, not truth — outputs must label them as such.
MULETILLAS: frozenset[str] = frozenset(
    {"eh", "ehh", "em", "este", "esto", "pues", "bueno", "o sea", "como que",
     "¿no?", "¿sabes?"}
)


def speech_time_s(segments: list[SpeechSegment]) -> float:
    """Σ VAD speech segment durations."""
    raise NotImplementedError


def wpm(n_words: int, seconds: float) -> float:
    """words / seconds × 60. Used for both gross (duration) and articulation
    (speech_time) rates; the gap between them is the hesitation profile."""
    raise NotImplementedError


def pauses(
    segments: list[SpeechSegment], duration_s: float, threshold_s: float
) -> tuple[int, float, float]:
    """VAD silences ≥ threshold → (pauses_n, pauses_total_s, pause_max_s).

    VAD is authoritative for pauses; word-gap pauses are only a cross-check.
    """
    raise NotImplementedError


def pauses_midclause_n(
    segments: list[SpeechSegment], words: list[Word], threshold_s: float
) -> int:
    """Pauses whose preceding transcribed word does not end a sentence
    (no trailing . ? !) — proxy for retrieval struggle."""
    raise NotImplementedError


def fillers_n(words: list[Word]) -> int:
    """Matches against MULETILLAS. Floor, not truth (whisper suppression)."""
    raise NotImplementedError


def ttr(lemmas: list[str]) -> float:
    """Type–token ratio over spaCy es_core_news_sm lemmas."""
    raise NotImplementedError


def mtld(lemmas: list[str], ttr_threshold: float = 0.72) -> float:
    """MTLD over lemmas — preferred over TTR (length-robust)."""
    raise NotImplementedError


def repeats_n(words: list[Word]) -> int:
    """Immediate repeated unigrams/bigrams — self-repair proxy."""
    raise NotImplementedError


def low_conf_spans(
    words: list[Word], prob_threshold: float
) -> list[tuple[float, float]]:
    """(start, end) of runs of consecutive words with prob < threshold.
    Fed to the LLM as "audio unclear here" hints; also flags mumbling."""
    raise NotImplementedError


def vad_transcript_gap_s(segments: list[SpeechSegment], words: list[Word]) -> float:
    """VAD speech time with few/no transcribed words — usually fillers or
    mumbling; surfaced as a data-quality note."""
    raise NotImplementedError


def compute_metrics(
    duration_s: float,
    segments: list[SpeechSegment],
    words: list[Word],
    lemmas: list[str],
    connector_matches: list[ConnectorMatch],
    thresholds: Thresholds,
) -> dict[str, float | int]:
    """Assemble the flat metrics dict (spec §2D table) from the parts above.

    Keys: duration_s, speech_time_s, wpm_gross, wpm_articulation, pauses_n,
    pauses_total_s, pause_max_s, pauses_midclause_n, fillers_n,
    fillers_per_min, connectors_unique_n, connectors_formal_ratio, ttr, mtld,
    repeats_n, low_conf_spans_n, vad_transcript_gap_s.

    TODO(implement).
    """
    raise NotImplementedError
