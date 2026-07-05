"""Runtime system-prompt builder.

Async wrapper over :func:`hable_ya.pipeline.prompts.render.render_system_prompt`.
On cold start (no pool, or ``sessions_completed == 0``) it returns the same
bytes the pre-029 neutral builder produced — spec-023 byte-identity tests in
``tests/test_prompts.py`` stay green. Once the learner has completed a
session, it pulls a :class:`LearnerProfileSnapshot` from the DB and maps it
into a :class:`LearnerProfile`, and picks a :class:`Theme` from
:mod:`hable_ya.learner.themes` that honours the cooldown window.

``build_system_prompt`` returns just the rendered string (used in tests and
cold paths). ``build_session_prompt`` returns a :class:`SessionPrompt` with
the same rendered string plus the resolved theme and band — the session
handler needs both to thread through to ``TurnIngestService.start_session``.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from eval.fixtures.schema import CEFRBand, LearnerProfile, SystemParams, Theme
from hable_ya.config import settings
from hable_ya.learner.profile import (
    LearnerProfileRepo,
    LearnerProfileSnapshot,
    is_calibrated_async,
    snapshot_to_profile,
)
from hable_ya.learner.themes import NEUTRAL_THEME as _NEUTRAL_THEME
from hable_ya.learner.themes import get_session_theme
from hable_ya.pipeline.prompts.register import COLD_START_INSTRUCTIONS
from hable_ya.pipeline.prompts.render import render_system_prompt


@dataclass(slots=True, frozen=True)
class SessionPrompt:
    text: str
    theme: Theme
    band: CEFRBand


def _neutral_profile(band: CEFRBand) -> LearnerProfile:
    return snapshot_to_profile(
        LearnerProfileSnapshot(band=band, sessions_completed=0),
        is_calibrated=False,
    )


def render_cold_start_prompt(band: CEFRBand) -> str:
    """Render the same system prompt the runtime emits on a fresh DB.

    Synchronous and DB-free so the replay script and tests can use it
    without a pool. Mirrors the uncalibrated branch of
    :func:`build_session_prompt`: neutral profile, neutral theme, the
    appended ``COLD_START_INSTRUCTIONS`` block.
    """
    params = SystemParams(profile=_neutral_profile(band), theme=_NEUTRAL_THEME)
    rendered = render_system_prompt(params, band=band)
    return f"{rendered}\n\n## Primera sesión\n{COLD_START_INSTRUCTIONS}"


async def build_session_prompt(
    learner: dict[str, object],
    *,
    pool: asyncpg.Pool | None = None,
    recent_domains: list[str] | None = None,
) -> SessionPrompt:
    opt_in_cold_start = bool(learner.get("cold_start"))

    if pool is None:
        band_raw = learner.get("band", "A2")
        band: CEFRBand = band_raw if isinstance(band_raw, str) else "A2"  # type: ignore[assignment]
        profile = _neutral_profile(band)
        theme = _NEUTRAL_THEME
    else:
        snapshot = await LearnerProfileRepo(pool).get(
            window_turns=settings.profile_window_turns,
            top_errors=settings.profile_top_errors,
            top_vocab=settings.profile_top_vocab,
        )
        band = snapshot.band
        # Spec 049: is_calibrated derives from "a placement row exists",
        # not from sessions_completed > 0. A session that wrote no
        # ``log_turn`` calls (pathological but possible) must not flip
        # the cold-start gate.
        calibrated = await is_calibrated_async(pool)
        profile = snapshot_to_profile(snapshot, is_calibrated=calibrated)
        opt_in_cold_start = opt_in_cold_start or not calibrated
        theme = (
            _NEUTRAL_THEME
            if not calibrated
            else get_session_theme(
                level=band,
                recent_domains=recent_domains or [],
                cooldown=settings.theme_cooldown,
            )
        )

    params = SystemParams(profile=profile, theme=theme)
    rendered = render_system_prompt(params, band=band)
    if opt_in_cold_start:
        rendered = f"{rendered}\n\n## Primera sesión\n{COLD_START_INSTRUCTIONS}"
    return SessionPrompt(text=rendered, theme=theme, band=band)


__all__ = [
    "SessionPrompt",
    "build_session_prompt",
    "build_system_prompt",
    "render_cold_start_prompt",
]


async def build_system_prompt(
    learner: dict[str, object],
    *,
    pool: asyncpg.Pool | None = None,
    recent_domains: list[str] | None = None,
) -> str:
    session_prompt = await build_session_prompt(
        learner, pool=pool, recent_domains=recent_domains
    )
    return session_prompt.text
