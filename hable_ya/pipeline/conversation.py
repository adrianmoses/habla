"""Per-session conversation configuration (spec 023).

A learner can steer a session into a debate, role-play, or interview — or the
default open chat — with an optional freeform topic, chosen once at session
start via ``/ws/session`` query params. This module holds the value object and
its fail-safe parser. The mapping from a config to the :class:`Theme` that
fills the prompt's ``## Topic:`` block lives in :mod:`hable_ya.learner.modes`;
nothing here touches the register / rubric / recast / ``log_turn`` blocks, so
the learner-model loop runs identically under any mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from eval.fixtures.schema import ConversationMode

VALID_MODES: frozenset[str] = frozenset(get_args(ConversationMode))
DEFAULT_MODE: ConversationMode = "open"


@dataclass(slots=True, frozen=True)
class ConversationConfig:
    """A session's requested mode + optional freeform topic."""

    mode: ConversationMode = DEFAULT_MODE
    topic: str | None = None


def parse_conversation_config(
    mode_raw: str | None, topic_raw: str | None
) -> ConversationConfig:
    """Normalize raw query-param values into a :class:`ConversationConfig`.

    Fail-safe by design: an unknown or blank ``mode`` falls back to ``open``,
    and a blank / whitespace-only ``topic`` becomes ``None``. Never raises — a
    malformed query string must not break the WebSocket handshake.
    """
    mode: ConversationMode = (
        mode_raw  # type: ignore[assignment]
        if mode_raw in VALID_MODES
        else DEFAULT_MODE
    )
    topic = topic_raw.strip() if topic_raw else ""
    return ConversationConfig(mode=mode, topic=topic or None)
