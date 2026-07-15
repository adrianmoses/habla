"""parse_conversation_config normalization (spec 023)."""

from __future__ import annotations

import pytest

from hable_ya.pipeline.conversation import (
    DEFAULT_MODE,
    ConversationConfig,
    parse_conversation_config,
)


def test_defaults_to_open_with_no_topic() -> None:
    cfg = parse_conversation_config(None, None)
    assert cfg == ConversationConfig(mode="open", topic=None)
    assert cfg.mode == DEFAULT_MODE


@pytest.mark.parametrize("mode", ["open", "debate", "role_play", "interview"])
def test_valid_modes_pass_through(mode: str) -> None:
    assert parse_conversation_config(mode, None).mode == mode


@pytest.mark.parametrize("bogus", ["", "DEBATE", "chat", "role-play", "xyz"])
def test_unknown_mode_falls_back_to_open(bogus: str) -> None:
    assert parse_conversation_config(bogus, "el clima").mode == "open"


def test_topic_is_stripped_and_preserved() -> None:
    assert parse_conversation_config("debate", "  el teletrabajo  ").topic == (
        "el teletrabajo"
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n "])
def test_blank_topic_becomes_none(blank: str) -> None:
    assert parse_conversation_config("debate", blank).topic is None


def test_open_with_topic_is_honoured() -> None:
    cfg = parse_conversation_config("open", "la cocina")
    assert cfg.mode == "open"
    assert cfg.topic == "la cocina"


def test_config_is_frozen() -> None:
    cfg = parse_conversation_config("debate", "x")
    with pytest.raises(AttributeError):
        cfg.mode = "interview"  # type: ignore[misc]
