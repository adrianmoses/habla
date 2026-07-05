"""build_system_prompt() output tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from eval.fixtures.schema import CEFRBand, LearnerProfile, SystemParams, Theme
from hable_ya.learner.bands import ALL_BANDS as VALID_CEFR_BANDS
from hable_ya.learner.profile import _BAND_MIDPOINT, LearnerProfileSnapshot
from hable_ya.learner.themes import NEUTRAL_THEME as _NEUTRAL_THEME
from hable_ya.pipeline.prompts.builder import build_system_prompt
from hable_ya.pipeline.prompts.register import (
    COLD_START_INSTRUCTIONS,
    REGISTER_BY_LEVEL,
)
from hable_ya.pipeline.prompts.render import (
    BAND_RUBRIC_GLOSS,
    BAND_RUBRIC_PARAGRAPH,
    CANONICAL_KEYS,
    FORBIDDEN_CORRECTION_PHRASES,
    REGISTER_GUIDANCE,
    render_system_prompt,
)
from hable_ya.tools.schema import LOG_TURN_TOOL

BANDS: tuple[CEFRBand, ...] = ("A1", "A2", "B1", "B2", "C1")


def _expected_params(band: CEFRBand) -> SystemParams:
    profile = LearnerProfile(
        production_level=_BAND_MIDPOINT[band],
        L1_reliance=0.5,
        speech_fluency=0.5,
        is_calibrated=False,
        sessions_completed=0,
        vocab_strengths=[],
        error_patterns=[],
    )
    return SystemParams(profile=profile, theme=_NEUTRAL_THEME)


@pytest.mark.parametrize("band", BANDS)
async def test_builder_matches_render_for_band(band: CEFRBand) -> None:
    expected = render_system_prompt(_expected_params(band), band=band)
    assert await build_system_prompt({"band": band}) == expected


async def test_builder_defaults_to_a2() -> None:
    expected = render_system_prompt(_expected_params("A2"), band="A2")
    assert await build_system_prompt({}) == expected


async def test_prompt_is_non_empty_and_about_spanish() -> None:
    prompt = await build_system_prompt({"band": "A2"})
    assert prompt
    assert "Spanish" in prompt


async def test_prompt_contains_canonical_log_turn_example() -> None:
    prompt = await build_system_prompt({"band": "A2"})
    # Spec 049: the canonical example now includes cefr_band.
    assert (
        'log_turn({"learner_utterance": "...", "errors": [...], '
        '"fluency_signal": "...", "L1_used": ..., "cefr_band": "..."})'
    ) in prompt


async def test_prompt_lists_forbidden_phrases() -> None:
    prompt = await build_system_prompt({"band": "A2"})
    for phrase in FORBIDDEN_CORRECTION_PHRASES:
        assert phrase in prompt


async def test_prompt_does_not_use_forbidden_phrases_in_instructions() -> None:
    # Forbidden phrases appear quoted inside `  "..."` list items. Outside
    # that list, none should appear as natural prose.
    prompt = await build_system_prompt({"band": "A2"})
    non_list_prose = "\n".join(
        line for line in prompt.splitlines() if not line.strip().startswith('"')
    )
    for phrase in FORBIDDEN_CORRECTION_PHRASES:
        assert phrase not in non_list_prose.lower()


@pytest.mark.parametrize("band", BANDS)
async def test_prompt_uses_band_register_guidance(band: CEFRBand) -> None:
    prompt = await build_system_prompt({"band": band})
    assert REGISTER_GUIDANCE[band] in prompt


def test_register_by_level_matches_render_module() -> None:
    assert REGISTER_BY_LEVEL == dict(REGISTER_GUIDANCE)


async def test_cold_start_opt_in_appends_guidance() -> None:
    warm = await build_system_prompt({"band": "A2"})
    cold = await build_system_prompt({"band": "A2", "cold_start": True})
    assert COLD_START_INSTRUCTIONS in cold
    assert COLD_START_INSTRUCTIONS not in warm
    assert cold.startswith(warm)


def test_cold_start_instructions_non_empty() -> None:
    assert COLD_START_INSTRUCTIONS.strip() != ""


def test_theme_is_neutral() -> None:
    assert isinstance(_NEUTRAL_THEME, Theme)
    assert _NEUTRAL_THEME.domain == "conversación abierta"


# ---- Profile-aware build_system_prompt (spec 029) ------------------------


class _FakePool:
    """Sentinel marking that a pool was provided; the builder only uses the
    pool via LearnerProfileRepo, which we monkeypatch in these tests."""


async def test_pool_with_zero_sessions_renders_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = LearnerProfileSnapshot(
        band="B1",
        sessions_completed=0,
    )
    mock_repo = AsyncMock()
    mock_repo.get.return_value = snapshot
    monkeypatch.setattr(
        "hable_ya.pipeline.prompts.builder.LearnerProfileRepo",
        lambda _pool: mock_repo,
    )
    # Spec 049: cold-start gate now keys on is_calibrated_async, not on
    # sessions_completed > 0. Force it False for the uncalibrated path.
    async def _is_calibrated_false(_pool: object) -> bool:
        return False

    monkeypatch.setattr(
        "hable_ya.pipeline.prompts.builder.is_calibrated_async",
        _is_calibrated_false,
    )
    # With no placement row, the builder picks the neutral theme — the
    # rendered prompt should match a neutral-params render at the
    # snapshot's band.
    prompt = await build_system_prompt({}, pool=_FakePool())
    params = SystemParams(
        profile=LearnerProfile(
            production_level=_BAND_MIDPOINT["B1"],
            L1_reliance=0.5,
            speech_fluency=0.5,
            is_calibrated=False,
            sessions_completed=0,
            vocab_strengths=[],
            error_patterns=[],
        ),
        theme=_NEUTRAL_THEME,
    )
    expected = render_system_prompt(params, band="B1")
    # The cold-start opt-in also appends guidance once sessions_completed == 0
    # and pool is provided — this is the "first session" behavior.
    assert prompt.startswith(expected)
    assert COLD_START_INSTRUCTIONS in prompt


async def test_pool_with_populated_profile_surfaces_errors_and_vocab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = LearnerProfileSnapshot(
        band="B1",
        sessions_completed=4,
        l1_reliance=0.3,
        speech_fluency=0.7,
        error_patterns=["ser_estar", "preposiciones", "gender"],
        vocab_strengths=["comer", "manzana", "día", "querer", "casa"],
    )
    mock_repo = AsyncMock()
    mock_repo.get.return_value = snapshot
    monkeypatch.setattr(
        "hable_ya.pipeline.prompts.builder.LearnerProfileRepo",
        lambda _pool: mock_repo,
    )

    async def _is_calibrated_true(_pool: object) -> bool:
        return True

    monkeypatch.setattr(
        "hable_ya.pipeline.prompts.builder.is_calibrated_async",
        _is_calibrated_true,
    )
    prompt = await build_system_prompt({}, pool=_FakePool(), recent_domains=[])
    assert "ser_estar" in prompt
    assert "comer" in prompt
    assert "manzana" in prompt
    # Calibrated → cold-start opt-in is NOT auto-added.
    assert COLD_START_INSTRUCTIONS not in prompt


# ---- Spec 049: BAND_RUBRIC + cefr_band schema --------------------------


@pytest.mark.parametrize("band", BANDS)
async def test_prompt_contains_band_rubric_paragraph_for_all_bands(
    band: CEFRBand,
) -> None:
    """Every band's full paragraph rubric is in the rendered prompt.

    Single source of truth: ``BAND_RUBRIC_PARAGRAPH``. If the constant
    drifts, the canonical-example test will catch it; if the renderer
    drops the section, this catches it.
    """
    prompt = await build_system_prompt({"band": band})
    for paragraph_band in VALID_CEFR_BANDS:
        assert BAND_RUBRIC_PARAGRAPH[paragraph_band] in prompt


async def test_prompt_contains_assessing_section_header() -> None:
    prompt = await build_system_prompt({"band": "A2"})
    assert "## Assessing the learner's level" in prompt


async def test_prompt_documents_cefr_band_argument() -> None:
    prompt = await build_system_prompt({"band": "A2"})
    assert "- cefr_band:" in prompt


def test_cold_start_instructions_walk_the_four_step_ladder() -> None:
    # Byte-identity assertion that the four-step diagnostic ladder is in
    # place — the spec acceptance criterion. Counts the four numbered
    # markers; full content is fixed by the constant.
    for marker in ("1.", "2.", "3.", "4."):
        assert f"\n{marker} " in COLD_START_INSTRUCTIONS
    # The ladder must mention ``cefr_band`` so the model knows to emit it
    # during the diagnostic, not just in the regular flow.
    assert "cefr_band" in COLD_START_INSTRUCTIONS


def test_log_turn_tool_includes_cefr_band_enum() -> None:
    properties = LOG_TURN_TOOL["function"]["parameters"]["properties"]  # type: ignore[index]
    assert "cefr_band" in properties
    assert properties["cefr_band"]["enum"] == list(VALID_CEFR_BANDS)
    assert "cefr_band" in LOG_TURN_TOOL["function"]["parameters"]["required"]  # type: ignore[index]


def test_canonical_keys_include_cefr_band() -> None:
    assert "cefr_band" in CANONICAL_KEYS


def test_band_rubric_gloss_covers_all_bands() -> None:
    assert set(BAND_RUBRIC_GLOSS) == set(VALID_CEFR_BANDS)
    for band in VALID_CEFR_BANDS:
        assert BAND_RUBRIC_GLOSS[band].strip() != ""


async def test_pool_passes_recent_domains_to_theme_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = LearnerProfileSnapshot(band="A1", sessions_completed=1)
    mock_repo = AsyncMock()
    mock_repo.get.return_value = snapshot
    monkeypatch.setattr(
        "hable_ya.pipeline.prompts.builder.LearnerProfileRepo",
        lambda _pool: mock_repo,
    )

    async def _is_calibrated_true(_pool: object) -> bool:
        return True

    monkeypatch.setattr(
        "hable_ya.pipeline.prompts.builder.is_calibrated_async",
        _is_calibrated_true,
    )
    observed_domains: list[list[str]] = []

    def recording_get_theme(
        *,
        level: CEFRBand,
        recent_domains: list[str],
        cooldown: int = 3,
    ) -> Theme:
        observed_domains.append(list(recent_domains))
        return _NEUTRAL_THEME.model_copy(update={"domain": "replaced"})

    monkeypatch.setattr(
        "hable_ya.pipeline.prompts.builder.get_session_theme",
        recording_get_theme,
    )
    await build_system_prompt({}, pool=_FakePool(), recent_domains=["a", "b"])
    assert observed_domains == [["a", "b"]]
