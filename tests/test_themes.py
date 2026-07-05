"""Theme rotation and cooldown logic."""

from __future__ import annotations

import random

import pytest

from eval.fixtures.schema import CEFRBand, Theme
from hable_ya.learner.themes import (
    NEUTRAL_THEME,
    THEMES_BY_LEVEL,
    get_session_theme,
)

BANDS: list[CEFRBand] = ["A1", "A2", "B1", "B2", "C1"]


def test_themes_populated_for_every_band() -> None:
    for band in BANDS:
        assert band in THEMES_BY_LEVEL
        assert len(THEMES_BY_LEVEL[band]) >= 8


def test_every_theme_has_domain_and_prompt() -> None:
    for band, themes in THEMES_BY_LEVEL.items():
        for theme in themes:
            assert isinstance(theme, Theme), band
            assert theme.domain.strip(), band
            assert theme.prompt.strip(), band


def test_domains_are_unique_within_a_band() -> None:
    for band, themes in THEMES_BY_LEVEL.items():
        domains = [t.domain for t in themes]
        assert len(set(domains)) == len(domains), band


def test_get_session_theme_returns_theme_from_pool() -> None:
    random.seed(0)
    theme = get_session_theme(level="A1", recent_domains=[])
    assert theme in THEMES_BY_LEVEL["A1"]


def test_get_session_theme_excludes_recent_domains() -> None:
    random.seed(0)
    pool = THEMES_BY_LEVEL["A2"]
    recent = [pool[0].domain, pool[1].domain, pool[2].domain]
    for _ in range(50):
        chosen = get_session_theme(level="A2", recent_domains=recent)
        assert chosen.domain not in recent


def test_cooldown_windows_only_the_last_three_entries() -> None:
    """With a long recent_domains list, only the final 3 count as cooldown."""
    random.seed(0)
    pool = THEMES_BY_LEVEL["B1"]
    # Fill the cooldown with domains NOT in the last 3 → selection can still
    # return any of the first ones.
    old_blocked = [t.domain for t in pool[:3]]
    fresh_blocked = [t.domain for t in pool[-3:]]
    recent = old_blocked + fresh_blocked
    seen: set[str] = set()
    for _ in range(100):
        chosen = get_session_theme(level="B1", recent_domains=recent)
        seen.add(chosen.domain)
    # At least one of the "old_blocked" entries should appear, proving the
    # cooldown only looked at the last 3.
    assert set(old_blocked) & seen


def test_pool_exhausted_falls_back_to_neutral() -> None:
    pool = THEMES_BY_LEVEL["A1"]
    recent = [t.domain for t in pool]
    chosen = get_session_theme(level="A1", recent_domains=recent, cooldown=len(pool))
    assert chosen is NEUTRAL_THEME


@pytest.mark.parametrize("band", BANDS)
def test_all_bands_selectable_with_empty_cooldown(band: CEFRBand) -> None:
    random.seed(0)
    chosen = get_session_theme(level=band, recent_domains=[])
    assert chosen.domain in {t.domain for t in THEMES_BY_LEVEL[band]}
