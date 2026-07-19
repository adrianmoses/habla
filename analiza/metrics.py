"""Metrics (spec §2D): pure functions over VAD segments + word list. No I/O.

Everything here must stay deterministic and reproducible across 90 days —
never route a metric through the LLM. Output is a flat dict → JSON.
"""

import string

from analiza.config import Thresholds
from analiza.connectors import ConnectorMatch, connectors_unique_n, formal_ratio
from analiza.transcribe import Word
from analiza.vad import SpeechSegment

# Filler inventory. Whisper suppresses fillers, so counts derived from this
# are a floor, not truth — outputs must label them as such.
MULETILLAS: frozenset[str] = frozenset(
    {"eh", "ehh", "em", "este", "esto", "pues", "bueno", "o sea", "como que",
     "¿no?", "¿sabes?"}
)

_STRIP_CHARS = string.punctuation + "¿¡…«»“”"

# Muletillas whose punctuation is significant ("¿no?" must not match a plain
# "no") are matched against the raw lowercased word; the rest against the
# punctuation-stripped token. Multiword entries match token bigrams.
_PHRASES = frozenset(m for m in MULETILLAS if " " in m)
_PUNCT_SINGLES = frozenset(
    m for m in MULETILLAS if " " not in m and m != m.strip(_STRIP_CHARS)
)
_PLAIN_SINGLES = frozenset(MULETILLAS - _PHRASES - _PUNCT_SINGLES)

# Word timestamps and VAD boundaries come from different models; allow this
# much skew when deciding which word precedes a pause.
_ALIGN_TOLERANCE_S = 0.3


def _norm(token: str) -> str:
    return token.lower().strip().strip(_STRIP_CHARS)


def speech_time_s(segments: list[SpeechSegment]) -> float:
    """Σ VAD speech segment durations."""
    return sum(seg.duration for seg in segments)


def wpm(n_words: int, seconds: float) -> float:
    """words / seconds × 60. Used for both gross (duration) and articulation
    (speech_time) rates; the gap between them is the hesitation profile."""
    if seconds <= 0:
        return 0.0
    return n_words / seconds * 60


def _silence_gaps(
    segments: list[SpeechSegment], duration_s: float
) -> list[tuple[float, float]]:
    """(start, end) of every silence: leading, inter-segment, trailing."""
    if not segments:
        return [(0.0, duration_s)] if duration_s > 0 else []
    gaps = [(0.0, segments[0].start)]
    gaps += [(a.end, b.start) for a, b in zip(segments, segments[1:], strict=False)]
    gaps.append((segments[-1].end, duration_s))
    return [(s, e) for s, e in gaps if e > s]


def pauses(
    segments: list[SpeechSegment], duration_s: float, threshold_s: float
) -> tuple[int, float, float]:
    """VAD silences ≥ threshold → (pauses_n, pauses_total_s, pause_max_s).

    VAD is authoritative for pauses; word-gap pauses are only a cross-check.
    """
    lengths = [
        e - s for s, e in _silence_gaps(segments, duration_s) if e - s >= threshold_s
    ]
    return len(lengths), sum(lengths), max(lengths, default=0.0)


def pauses_midclause_n(
    segments: list[SpeechSegment], words: list[Word], threshold_s: float
) -> int:
    """Pauses whose preceding transcribed word does not end a sentence
    (no trailing . ? !) — proxy for retrieval struggle."""
    n = 0
    for start, end in _silence_gaps(segments, duration_s=float("inf")):
        if end == float("inf") or end - start < threshold_s:
            continue  # trailing pseudo-gap or below threshold
        preceding = [w for w in words if w.end <= start + _ALIGN_TOLERANCE_S]
        if not preceding:
            continue  # leading silence: no word before it
        last = max(preceding, key=lambda w: w.end)
        if not last.text.rstrip().endswith((".", "?", "!")):
            n += 1
    return n


def fillers_n(words: list[Word]) -> int:
    """Matches against MULETILLAS. Floor, not truth (whisper suppression)."""
    raw = [w.text.lower().strip() for w in words]
    tokens = [_norm(w.text) for w in words]
    n = 0
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens) and f"{tokens[i]} {tokens[i + 1]}" in _PHRASES:
            n += 1
            i += 2
            continue
        if tokens[i] in _PLAIN_SINGLES or raw[i] in _PUNCT_SINGLES:
            n += 1
        i += 1
    return n


def ttr(lemmas: list[str]) -> float:
    """Type–token ratio over spaCy es_core_news_sm lemmas."""
    if not lemmas:
        return 0.0
    return len(set(lemmas)) / len(lemmas)


def _mtld_directional(lemmas: list[str], ttr_threshold: float) -> float:
    factors = 0.0
    types: set[str] = set()
    count = 0
    current_ttr = 1.0
    for lemma in lemmas:
        count += 1
        types.add(lemma)
        current_ttr = len(types) / count
        if current_ttr <= ttr_threshold:
            factors += 1
            types = set()
            count = 0
            current_ttr = 1.0
    if count > 0 and current_ttr < 1.0:
        factors += (1 - current_ttr) / (1 - ttr_threshold)  # partial factor
    if factors == 0:
        return float(len(lemmas))  # never dipped below threshold
    return len(lemmas) / factors


def mtld(lemmas: list[str], ttr_threshold: float = 0.72) -> float:
    """MTLD over lemmas — preferred over TTR (length-robust)."""
    if not lemmas:
        return 0.0
    forward = _mtld_directional(lemmas, ttr_threshold)
    backward = _mtld_directional(list(reversed(lemmas)), ttr_threshold)
    return (forward + backward) / 2


def repeats_n(words: list[Word]) -> int:
    """Immediate repeated unigrams/bigrams — self-repair proxy."""
    tokens = [t for t in (_norm(w.text) for w in words) if t]
    n = sum(1 for a, b in zip(tokens, tokens[1:], strict=False) if a == b)
    for i in range(len(tokens) - 3):
        # Bigram repeats, excluding runs already counted as unigram repeats.
        if (
            tokens[i] != tokens[i + 1]
            and tokens[i : i + 2] == tokens[i + 2 : i + 4]
        ):
            n += 1
    return n


def low_conf_spans(
    words: list[Word], prob_threshold: float
) -> list[tuple[float, float]]:
    """(start, end) of runs of ≥2 consecutive words with prob < threshold.
    Fed to the LLM as "audio unclear here" hints; also flags mumbling."""
    spans: list[tuple[float, float]] = []
    run: list[Word] = []
    for w in [*words, None]:
        if w is not None and w.prob < prob_threshold:
            run.append(w)
            continue
        if len(run) >= 2:
            spans.append((run[0].start, run[-1].end))
        run = []
    return spans


def vad_transcript_gap_s(segments: list[SpeechSegment], words: list[Word]) -> float:
    """VAD speech time with few/no transcribed words — usually fillers or
    mumbling; surfaced as a data-quality note."""
    gap = 0.0
    for seg in segments:
        overlap = sum(
            max(0.0, min(w.end, seg.end) - max(w.start, seg.start)) for w in words
        )
        gap += max(0.0, seg.duration - overlap)
    return gap


def compute_metrics(
    duration_s: float,
    segments: list[SpeechSegment],
    words: list[Word],
    lemmas: list[str],
    connector_matches: list[ConnectorMatch],
    thresholds: Thresholds,
) -> dict[str, float | int]:
    """Assemble the flat metrics dict (spec §2D table) from the parts above."""
    speech_s = speech_time_s(segments)
    n_words = len(words)
    n_pauses, pauses_total, pause_max = pauses(
        segments, duration_s, thresholds.pause_s
    )
    n_fillers = fillers_n(words)
    return {
        "duration_s": round(duration_s, 2),
        "speech_time_s": round(speech_s, 2),
        "wpm_gross": round(wpm(n_words, duration_s), 1),
        "wpm_articulation": round(wpm(n_words, speech_s), 1),
        "pauses_n": n_pauses,
        "pauses_total_s": round(pauses_total, 2),
        "pause_max_s": round(pause_max, 2),
        "pauses_midclause_n": pauses_midclause_n(
            segments, words, thresholds.pause_s
        ),
        "fillers_n": n_fillers,
        "fillers_per_min": round(wpm(n_fillers, duration_s), 2),
        "connectors_unique_n": connectors_unique_n(connector_matches),
        "connectors_formal_ratio": round(formal_ratio(connector_matches), 3),
        "ttr": round(ttr(lemmas), 3),
        "mtld": round(mtld(lemmas), 1),
        "repeats_n": repeats_n(words),
        "low_conf_spans_n": len(low_conf_spans(words, thresholds.low_conf_prob)),
        "vad_transcript_gap_s": round(vad_transcript_gap_s(segments, words), 2),
    }
