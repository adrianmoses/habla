"""Display-name normalization (spec #021) — pure, no DB.

`normalize_display_name` is the whole product rule for what a learner may call
themselves, so it is tested directly rather than through HTTP. The endpoint
tests in `test_learner_api.py` cover the wiring; these cover the rule.
"""

from __future__ import annotations

import pytest

from hable_ya.learner.identity import (
    MAX_DISPLAY_NAME,
    InvalidDisplayName,
    normalize_display_name,
)

# --------------------------------------------------------------------------- #
# Clearing — "not set" has to stay representable
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n ", " "])
def test_empty_inputs_clear_the_name(raw: str | None) -> None:
    assert normalize_display_name(raw) is None


# --------------------------------------------------------------------------- #
# Trimming
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ana", "Ana"),
        ("  Ana  ", "Ana"),
        ("\tAna\n", "Ana"),
        ("Ana María", "Ana María"),  # internal spaces survive
    ],
)
def test_surrounding_whitespace_is_trimmed(raw: str, expected: str) -> None:
    assert normalize_display_name(raw) == expected


def test_trimming_happens_before_the_length_check() -> None:
    # 40 characters plus padding: valid, because the bound is on the trimmed
    # value. This is the case a raw `max_length` on the request model gets
    # wrong.
    padded = "  " + "a" * MAX_DISPLAY_NAME + "  "
    assert normalize_display_name(padded) == "a" * MAX_DISPLAY_NAME


# --------------------------------------------------------------------------- #
# Length bound
# --------------------------------------------------------------------------- #


def test_name_at_the_limit_is_accepted() -> None:
    name = "a" * MAX_DISPLAY_NAME
    assert normalize_display_name(name) == name


def test_name_over_the_limit_is_rejected() -> None:
    with pytest.raises(InvalidDisplayName):
        normalize_display_name("a" * (MAX_DISPLAY_NAME + 1))


def test_length_is_counted_in_code_points_not_utf16_units() -> None:
    # Each of these is one code point but two UTF-16 units; counting units
    # would reject a name that is half the limit.
    name = "\U0001f600" * MAX_DISPLAY_NAME
    assert normalize_display_name(name) == name


# --------------------------------------------------------------------------- #
# Control and formatting characters
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    [
        "An\x00a",  # NUL (Cc)
        "An\x07a",  # BEL (Cc)
        "Ana\x1b[31m",  # ANSI escape (Cc)
        "An\u200ba",  # zero-width space (Cf)
        "An\u200da",  # zero-width joiner (Cf)
        "An\u202ea",  # right-to-left override (Cf) — spoofs the rendered order
        "\ufeffAna",  # BOM (Cf)
    ],
)
def test_control_and_formatting_characters_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidDisplayName):
        normalize_display_name(raw)


def test_interior_newline_is_rejected() -> None:
    # `.strip()` would only take newlines off the ends; an interior one would
    # break the greeting's layout, and it is a Cc character anyway.
    with pytest.raises(InvalidDisplayName):
        normalize_display_name("Ana\nMaría")


# --------------------------------------------------------------------------- #
# No character allowlist: scripts and accents must all work
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "Ángela",
        "José-María",
        "O'Brien",
        "Ana 2",
        "안나",
        "Анна",
        "الاسم",
        "\U0001f600 Ana",  # non-BMP first code point
        "Ana; DROP TABLE learner_profile--",  # parameterized, never cypher
    ],
)
def test_unicode_and_punctuation_round_trip(name: str) -> None:
    assert normalize_display_name(name) == name
