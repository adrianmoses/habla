"""Metrics tests (spec §2D / §3 — pure functions, no audio needed).

Planned fixtures (spec §3): 3–4 hand-annotated short recordings — one clean,
one filler-heavy, one with long pauses, one mumbled — with expected metric
ranges, checked in under tests/fixtures/analiza/ once recorded. The tests
below cover the pure functions synthetically; unskip as metrics.py lands.
"""

import pytest

from analiza import metrics
from analiza.vad import SpeechSegment


@pytest.mark.skip(reason="scaffold: implement metrics.speech_time_s")
def test_speech_time_sums_segments() -> None:
    segs = [SpeechSegment(0.0, 2.0), SpeechSegment(3.0, 4.5)]
    assert metrics.speech_time_s(segs) == pytest.approx(3.5)


@pytest.mark.skip(reason="scaffold: implement metrics.wpm")
def test_wpm() -> None:
    assert metrics.wpm(n_words=120, seconds=60.0) == pytest.approx(120.0)


@pytest.mark.skip(reason="scaffold: implement metrics.pauses")
def test_pauses_respects_threshold() -> None:
    # Gaps: 1.0s (counts), 0.5s (below 0.7 threshold), trailing 2.0s (counts).
    segs = [SpeechSegment(0.0, 2.0), SpeechSegment(3.0, 5.0), SpeechSegment(5.5, 8.0)]
    n, total, longest = metrics.pauses(segs, duration_s=10.0, threshold_s=0.7)
    assert n == 2
    assert longest == pytest.approx(2.0)


@pytest.mark.skip(reason="scaffold: implement metrics.mtld")
def test_mtld_is_length_robust() -> None:
    lemmas = ["ir", "casa", "comer", "bien"] * 25
    doubled = lemmas * 2
    assert metrics.mtld(doubled) == pytest.approx(metrics.mtld(lemmas), rel=0.1)
