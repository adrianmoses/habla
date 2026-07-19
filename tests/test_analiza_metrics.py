"""Metrics tests (spec §2D / §3 — pure functions, no audio needed).

Planned fixtures (spec §3): 3–4 hand-annotated short recordings — one clean,
one filler-heavy, one with long pauses, one mumbled — with expected metric
ranges, checked in under tests/fixtures/analiza/ once recorded. The tests
below cover the pure functions synthetically.
"""

import pytest

from analiza import metrics
from analiza.config import Thresholds
from analiza.transcribe import Word
from analiza.vad import SpeechSegment


def w(text: str, start: float, end: float, prob: float = 0.95) -> Word:
    return Word(text=text, start=start, end=end, prob=prob)


def test_speech_time_sums_segments() -> None:
    segs = [SpeechSegment(0.0, 2.0), SpeechSegment(3.0, 4.5)]
    assert metrics.speech_time_s(segs) == pytest.approx(3.5)


def test_wpm() -> None:
    assert metrics.wpm(n_words=120, seconds=60.0) == pytest.approx(120.0)


def test_wpm_zero_seconds_is_zero() -> None:
    assert metrics.wpm(n_words=10, seconds=0.0) == 0.0


def test_pauses_respects_threshold() -> None:
    # Gaps: 1.0s (counts), 0.5s (below 0.7 threshold), trailing 2.0s (counts).
    segs = [SpeechSegment(0.0, 2.0), SpeechSegment(3.0, 5.0), SpeechSegment(5.5, 8.0)]
    n, total, longest = metrics.pauses(segs, duration_s=10.0, threshold_s=0.7)
    assert n == 2
    assert total == pytest.approx(3.0)
    assert longest == pytest.approx(2.0)


def test_pauses_leading_silence_counts() -> None:
    segs = [SpeechSegment(1.5, 5.0)]
    n, total, longest = metrics.pauses(segs, duration_s=5.0, threshold_s=0.7)
    assert n == 1
    assert longest == pytest.approx(1.5)


def test_pauses_no_segments_is_one_long_silence() -> None:
    n, total, longest = metrics.pauses([], duration_s=4.0, threshold_s=0.7)
    assert (n, total, longest) == (1, pytest.approx(4.0), pytest.approx(4.0))


def test_pauses_midclause_counts_only_unterminated() -> None:
    segs = [SpeechSegment(0.0, 2.0), SpeechSegment(3.0, 5.0), SpeechSegment(6.0, 8.0)]
    words = [w("fui a", 0.0, 1.0), w("la", 1.0, 2.0),  # midclause pause after
             w("tienda.", 3.0, 5.0),                   # sentence-final pause after
             w("luego", 6.0, 8.0)]
    assert metrics.pauses_midclause_n(segs, words, threshold_s=0.7) == 1


def test_pauses_midclause_leading_silence_ignored() -> None:
    segs = [SpeechSegment(2.0, 5.0)]
    words = [w("hola", 2.0, 5.0)]
    assert metrics.pauses_midclause_n(segs, words, threshold_s=0.7) == 0


def test_fillers_unigram_bigram_and_punctuation() -> None:
    words = [
        w("Bueno,", 0, 1),      # plain single, punctuation stripped
        w("o", 1, 2), w("sea", 2, 3),  # bigram phrase
        w("no", 3, 4),          # plain "no" must NOT match "¿no?"
        w("¿no?", 4, 5),        # punctuation-significant single
        w("casa", 5, 6),
    ]
    assert metrics.fillers_n(words) == 3


def test_ttr() -> None:
    assert metrics.ttr(["ir", "casa", "ir"]) == pytest.approx(2 / 3)
    assert metrics.ttr([]) == 0.0


def test_mtld_is_length_robust() -> None:
    lemmas = ["ir", "casa", "comer", "bien"] * 25
    doubled = lemmas * 2
    assert metrics.mtld(doubled) == pytest.approx(metrics.mtld(lemmas), rel=0.1)


def test_mtld_higher_for_more_diverse_text() -> None:
    diverse = [f"lemma{i}" for i in range(100)]
    repetitive = ["ir", "casa"] * 50
    assert metrics.mtld(diverse) > metrics.mtld(repetitive)


def test_repeats_counts_unigram_and_bigram() -> None:
    words = [w(t, i, i + 1) for i, t in enumerate(
        ["yo", "yo", "fui", "a", "la", "a", "la", "tienda"]
    )]
    # "yo yo" (unigram) + "a la a la" (bigram) = 2
    assert metrics.repeats_n(words) == 2


def test_low_conf_spans_requires_run_of_two() -> None:
    words = [
        w("claro", 0, 1, prob=0.9),
        w("mm", 1, 2, prob=0.3),    # lone low-conf word: no span
        w("bien", 2, 3, prob=0.9),
        w("algo", 3, 4, prob=0.2),  # run of two → span
        w("raro", 4, 5, prob=0.4),
        w("fin", 5, 6, prob=0.9),
    ]
    assert metrics.low_conf_spans(words, prob_threshold=0.5) == [(3.0, 5.0)]


def test_vad_transcript_gap() -> None:
    segs = [SpeechSegment(0.0, 4.0)]
    words = [w("hola", 0.0, 1.0), w("adiós", 3.0, 4.0)]  # 2s of speech untranscribed
    assert metrics.vad_transcript_gap_s(segs, words) == pytest.approx(2.0)


def test_compute_metrics_has_contract_keys() -> None:
    segs = [SpeechSegment(0.0, 30.0), SpeechSegment(31.0, 60.0)]
    tokens = ["hola", "pues", "fui", "a", "casa"]
    words = [w(t, i, i + 0.5) for i, t in enumerate(tokens)]
    result = metrics.compute_metrics(
        duration_s=60.0,
        segments=segs,
        words=words,
        lemmas=["hola", "pues", "ir", "a", "casa"],
        connector_matches=[],
        thresholds=Thresholds(),
    )
    assert set(result) == {
        "duration_s", "speech_time_s", "wpm_gross", "wpm_articulation",
        "pauses_n", "pauses_total_s", "pause_max_s", "pauses_midclause_n",
        "fillers_n", "fillers_per_min", "connectors_unique_n",
        "connectors_formal_ratio", "ttr", "mtld", "repeats_n",
        "low_conf_spans_n", "vad_transcript_gap_s",
    }
    assert result["wpm_gross"] == pytest.approx(5.0)
    assert result["fillers_n"] == 1  # "pues"
