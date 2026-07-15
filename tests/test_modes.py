"""build_mode_theme factories (spec 023)."""

from __future__ import annotations

import pytest

from eval.fixtures.schema import CEFRBand, Theme
from hable_ya.learner.modes import build_mode_theme
from hable_ya.pipeline.conversation import ConversationConfig

BANDS: tuple[CEFRBand, ...] = ("A1", "A2", "B1", "B2", "C1")


def _theme(mode: str, topic: str | None, *, level: CEFRBand = "A2") -> Theme:
    return build_mode_theme(
        ConversationConfig(mode=mode, topic=topic),  # type: ignore[arg-type]
        level=level,
        recent_domains=[],
        cooldown=3,
    )


# ---- open -----------------------------------------------------------------


def test_open_without_topic_delegates_to_get_session_theme() -> None:
    # No topic → a real pool theme for the band (delegation), not a slug.
    theme = _theme("open", None, level="A1")
    assert isinstance(theme, Theme)
    assert not theme.domain.startswith("open:")


def test_open_with_topic_steers_conversation() -> None:
    theme = _theme("open", "la cocina")
    assert theme.domain == "la cocina"
    assert "la cocina" in theme.prompt
    assert theme.target_structures == []


# ---- parametric modes -----------------------------------------------------


@pytest.mark.parametrize("mode", ["debate", "role_play", "interview"])
def test_topic_appears_in_prompt(mode: str) -> None:
    theme = _theme(mode, "el medio ambiente")
    assert "el medio ambiente" in theme.prompt


@pytest.mark.parametrize("mode", ["debate", "role_play", "interview"])
def test_domain_slug_with_and_without_topic(mode: str) -> None:
    assert _theme(mode, "el teletrabajo").domain == f"{mode}: el teletrabajo"
    assert _theme(mode, None).domain == mode


@pytest.mark.parametrize("mode", ["debate", "role_play", "interview"])
def test_no_topic_still_produces_a_prompt(mode: str) -> None:
    theme = _theme(mode, None)
    assert theme.prompt.strip() != ""


# ---- level scales hints, never gates the mode -----------------------------


@pytest.mark.parametrize("mode", ["debate", "interview"])
def test_abstract_modes_have_per_band_hints(mode: str) -> None:
    seen: list[list[str]] = []
    for band in BANDS:
        theme = _theme(mode, "x", level=band)
        assert theme.target_structures, f"{mode}/{band} should have hints"
        seen.append(theme.target_structures)
    # Hints genuinely differ across bands (scaling), not one repeated list.
    assert any(seen[0] != s for s in seen[1:])


def test_role_play_has_no_target_hints_at_any_band() -> None:
    for band in BANDS:
        assert _theme("role_play", "una tienda", level=band).target_structures == []


def test_debate_is_available_at_a1_no_gating() -> None:
    # The whole point of spec 023: a debate renders at A1 exactly as at C1.
    theme = _theme("debate", "perros o gatos", level="A1")
    assert "perros o gatos" in theme.prompt
    assert theme.target_structures  # A1 hints exist
