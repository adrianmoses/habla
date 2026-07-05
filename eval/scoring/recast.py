"""recast_present and recast_explicit checks."""

from __future__ import annotations

import functools
import re
import warnings

# POS tags that carry the corrected-form's identity. Excludes PRON (person
# flips like me/te/le are expected in recasts) and ADV (modifiers like
# `muy`/`siempre` get added/dropped freely). Also excludes function words.
_CONTENT_POS = {"VERB", "AUX", "NOUN", "PROPN", "ADJ"}

# Spanish verb endings used to detect when spaCy returned the surface form
# instead of the infinitive (a known gap in `es_core_news_sm` for some
# 1st-person and irregular forms — e.g. `cocino` -> `cocino` instead of
# `cocinar`). When this happens we fall back to a 4-char stem prefix.
_VERB_SUFFIXES = (
    "ar",
    "er",
    "ir",
    "o",
    "as",
    "es",
    "amos",
    "emos",
    "imos",
    "an",
    "en",
    "aba",
    "ía",
    "ó",
    "é",
    "í",
)
_STEM_LEN = 4


@functools.lru_cache(maxsize=1)
def _nlp():
    """Lazy-load the Spanish spaCy model. Disable parser/NER (not needed)."""
    import spacy

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # silence model-version mismatch
        return spacy.load("es_core_news_sm", disable=["parser", "ner"])


def content_tokens(text: str) -> list[tuple[str, str]]:
    """Return content tokens as (lemma, stem) pairs.

    The stem is a 4-char prefix used as a fallback when spaCy lemmatization
    misfires (the Spanish small model often returns the surface form for
    1st-person verbs like `cocino` instead of `cocinar`, and inconsistently
    mangles `estudies` to `estudiser` in some contexts). A token is
    considered to match if EITHER its lemma OR its stem appears in the
    other side's lemma/stem set.
    """
    if not text or not text.strip():
        return []
    out: list[tuple[str, str]] = []
    for tok in _nlp()(text):
        if tok.pos_ not in _CONTENT_POS or not tok.is_alpha:
            continue
        lemma = tok.lemma_.lower()
        stem = lemma[:_STEM_LEN] if len(lemma) >= _STEM_LEN else lemma
        out.append((lemma, stem))
    return out


def content_lemma_surfaces(text: str) -> list[tuple[str, str]]:
    """Return content tokens as (lemma, first-seen surface form) pairs.

    Shares the POS filter + is_alpha guard with `content_tokens` but keeps
    the original surface token instead of the 4-char stem. Used by the
    runtime vocabulary writer, which records both the canonical lemma
    (primary key) and one sample surface form for human inspection.
    """
    if not text or not text.strip():
        return []
    seen: dict[str, str] = {}
    for tok in _nlp()(text):
        if tok.pos_ not in _CONTENT_POS or not tok.is_alpha:
            continue
        lemma = tok.lemma_.lower()
        if lemma and lemma not in seen:
            seen[lemma] = tok.text
    return list(seen.items())


def _all_keys(tokens: list[tuple[str, str]]) -> set[str]:
    out: set[str] = set()
    for lemma, stem in tokens:
        out.add(lemma)
        out.add(stem)
    return out


def _matches(target: str, response_keys: set[str]) -> bool:
    """A target matches if a majority of its content tokens appear in response.

    Each target token "appears" if its lemma OR its stem-prefix is in
    response_keys. Requires ≥50% of target tokens to match — strict subset
    is too rigid for natural recasts, which routinely drop one modifier.
    """
    tgt_tokens = content_tokens(target)
    if not tgt_tokens:
        return False
    matched = sum(
        1
        for lemma, stem in tgt_tokens
        if lemma in response_keys or stem in response_keys
    )
    return matched * 2 >= len(tgt_tokens)


_EXPLICIT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"no se dice",
        r"la forma correcta",
        r"debes decir",
        r"deberías decir",
        r"se dice",
        r"la palabra correcta",
        r"en realidad es",
        r"quieres decir",
        r"quisiste decir",
        r"correcto es",
        r"\berror\b",
    ]
]


def recast_present(
    response: str,
    recast_form: str | None,
    target_forms: list[str] | None = None,
) -> bool:
    """Check whether the model wove the corrected form into its reply.

    Uses spaCy lemmatization to handle the natural-recast patterns that
    plain substring matching misses:
      - person flips: target `me duele la cabeza` -> prose `le duele la cabeza`
      - conjugation: target `cocino` -> prose `cocinas` (lemma `cocinar`)
      - dropped subject: target `tú tienes` -> prose `tienes`
      - inserted/dropped modifiers: `estoy muy cansado` -> `estás cansado`

    Passes if EITHER:
      - the scaffolded `recast_form`'s content lemmas are a subset of the
        response's content lemmas, OR
      - any single `target`'s content lemmas are a subset of response lemmas.

    Returns True trivially when there's no expected form (no error to recast).
    """
    if recast_form is None and not target_forms:
        return True

    response_keys = _all_keys(content_tokens(response))
    if not response_keys:
        return False

    candidates: list[str] = []
    if recast_form:
        candidates.append(recast_form)
    if target_forms:
        candidates.extend(t for t in target_forms if t)

    return any(_matches(c, response_keys) for c in candidates)


def recast_explicit(response: str) -> bool:
    """Return True if the response contains explicit correction language.

    A return value of True is *bad* — the model is correcting explicitly
    rather than recasting naturally.
    """
    return any(p.search(response) for p in _EXPLICIT_PATTERNS)


def error_repeated(response: str, error_forms: list[str]) -> bool:
    """Return True if the model reproduces any of the learner's error forms.

    A return value of True is a hard failure — the agent should never
    reproduce the learner's mistake.
    """
    lower = response.lower()
    return any(form.lower() in lower for form in error_forms if form)
