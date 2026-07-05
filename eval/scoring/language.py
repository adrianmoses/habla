"""contains_english() detection."""

from __future__ import annotations

from langdetect import detect_langs
from langdetect.lang_detect_exception import LangDetectException


def contains_english(text: str) -> bool:
    """Return True if the response contains English.

    A return value of True is *bad* — the agent should stay in Spanish.
    Skips detection for very short text (< 15 chars) since langdetect
    is unreliable on short strings.
    """
    if len(text.strip()) < 15:
        return False
    try:
        langs = detect_langs(text)
    except LangDetectException:
        return False
    return any(lang.lang == "en" and lang.prob > 0.3 for lang in langs)
