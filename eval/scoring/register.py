"""check_register_heuristic()"""

from __future__ import annotations

import re
from typing import Literal

CEFRBand = Literal["A1", "A2", "B1", "B2", "C1"]

# (max_avg_word_len, max_words_per_sentence, max_rare_word_ratio)
# Spanish words run ~1 char longer than English on average, and many
# foundational A1/A2 nouns/verbs are 9-10 chars (`tranquilo`, `arquitecto`,
# `ejercicio`). The proper fix is a frequency-based lexicon; in the meantime
# bumped A1 ratio 0.05->0.10 and the rare-length cutoff 8->10 (see _RARE_LEN).
_BAND_THRESHOLDS: dict[CEFRBand, tuple[float, int, float]] = {
    "A1": (5.5, 10, 0.10),
    "A2": (6.0, 14, 0.10),
    "B1": (6.5, 18, 0.15),
    "B2": (7.0, 22, 0.25),
    "C1": (8.0, 30, 0.40),
}

_RARE_LEN = 10


# Strip leading/trailing punctuation so attached marks (`Entiendo,`,
# `cafeterías.`, `¿Hay`) don't inflate word length and trip the rare-word
# threshold. Keeps internal apostrophes/hyphens intact.
_PUNCT_STRIP_RE = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [w for w in (_PUNCT_STRIP_RE.sub("", t) for t in text.split()) if w]


def check_register_heuristic(text: str, band: CEFRBand) -> bool:
    """Return True if the response's complexity roughly matches the CEFR band.

    Uses word-length and sentence-length as proxies for vocabulary complexity.
    Deliberately lenient — catches egregious mismatches like C1 vocabulary in
    an A1 response.
    """
    words = _tokenize(text)
    if not words:
        return True

    max_avg_word_len, max_sent_len, max_rare_ratio = _BAND_THRESHOLDS[band]

    avg_word_len = sum(len(w) for w in words) / len(words)
    if avg_word_len > max_avg_word_len:
        return False

    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if sentences:
        max_words_in_sentence = max(len(_tokenize(s)) for s in sentences)
        if max_words_in_sentence > max_sent_len:
            return False

    rare_count = sum(1 for w in words if len(w) > _RARE_LEN)
    rare_ratio = rare_count / len(words)
    if rare_ratio > max_rare_ratio:
        return False

    return True
