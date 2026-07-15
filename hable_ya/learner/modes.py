"""Conversation-mode → :class:`Theme` factories (spec 023).

A "mode" is only an alternative way to construct the :class:`Theme` that fills
the prompt's ``## Topic:`` block (see :func:`render_system_prompt`). The
register / rubric / recast / ``log_turn`` blocks are band-driven and untouched,
so the learner-model loop runs identically under any mode.

Level scales **only the tutor's own language** (via those band blocks) plus,
for the abstract modes (``debate`` / ``interview``), a small per-band
``target_structures`` elicitation hint — it never gates mode availability. A
debate is offered at A1 exactly as at C1; only the language the tutor uses (and
these hints) differ.
"""

from __future__ import annotations

from collections.abc import Callable

from eval.fixtures.schema import CEFRBand, ConversationMode, Theme
from hable_ya.learner.themes import get_session_theme
from hable_ya.pipeline.conversation import ConversationConfig

# Per-band elicitation hints for the two abstract modes. role_play / open ship
# with no hints (the band register block already scales the tutor); empty lists
# render nothing (render.py only emits the line `if t.target_structures`).
_DEBATE_TARGETS: dict[CEFRBand, list[str]] = {
    "A1": ["(no) me gusta", "porque", "y / pero"],
    "A2": ["creo que", "porque", "(no) estoy de acuerdo"],
    "B1": ["opino que", "sin embargo", "por un lado / por otro lado"],
    "B2": ["aunque + subjuntivo", "no obstante", "en cambio", "a pesar de"],
    "C1": ["si bien", "por más que + subjuntivo", "cabe señalar", "no obstante"],
}
_INTERVIEW_TARGETS: dict[CEFRBand, list[str]] = {
    "A1": ["presente de indicativo", "¿cómo / dónde / qué...?", "gustar"],
    "A2": ["pretérito perfecto", "¿por qué...?", "expresar preferencias"],
    "B1": ["indefinido / imperfecto", "contar una experiencia", "porque / cuando"],
    "B2": ["condicional", "hipótesis con si", "matizar opiniones"],
    "C1": [
        "subjuntivo en subordinadas",
        "discurso indirecto",
        "conectores de precisión",
    ],
}
_TARGETS: dict[ConversationMode, dict[CEFRBand, list[str]]] = {
    "debate": _DEBATE_TARGETS,
    "interview": _INTERVIEW_TARGETS,
}


def _debate_prompt(topic: str | None) -> str:
    if topic is not None:
        return (
            f"Mantén un debate con el estudiante sobre {topic}. Defiende una "
            "postura clara y contraria a la suya para que tenga que argumentar; "
            "pídele razones y ejemplos. Sé respetuoso y adapta tu lenguaje a su "
            "nivel. Haz una sola pregunta a la vez."
        )
    return (
        "Mantén un debate con el estudiante sobre un tema cotidiano y "
        "discutible apropiado a su nivel. Propón el tema, defiende una postura "
        "contraria a la suya y pídele que argumente con razones y ejemplos. "
        "Haz una sola pregunta a la vez."
    )


def _role_play_prompt(topic: str | None) -> str:
    if topic is not None:
        return (
            f"Representa un juego de rol con el estudiante. Escenario: {topic}. "
            "Adopta tu papel con naturalidad, mantente en personaje y deja que "
            "el estudiante intente lograr su objetivo. Haz una sola pregunta a "
            "la vez."
        )
    return (
        "Representa un juego de rol cotidiano apropiado a su nivel (una tienda, "
        "un restaurante, el médico, una oficina...). Propón el escenario, "
        "adopta un papel y deja que el estudiante participe. Mantente en "
        "personaje y haz una sola pregunta a la vez."
    )


def _interview_prompt(topic: str | None) -> str:
    if topic is not None:
        return (
            f"Entrevista al estudiante sobre {topic}. Adopta el papel de "
            "entrevistador y haz preguntas claras, una a la vez, profundizando "
            "en sus respuestas. Adapta tu lenguaje a su nivel."
        )
    return (
        "Entrevista al estudiante sobre su vida, sus intereses o su "
        "experiencia, apropiado a su nivel. Adopta el papel de entrevistador y "
        "haz preguntas claras, una a la vez, profundizando en sus respuestas."
    )


def _open_prompt(topic: str) -> str:
    return (
        f"Mantén una conversación natural con el estudiante centrada en {topic}. "
        "Haz preguntas abiertas y deja que el estudiante lleve la iniciativa. "
        "Haz una sola pregunta a la vez."
    )


_MODE_PROMPTS: dict[ConversationMode, Callable[[str | None], str]] = {
    "debate": _debate_prompt,
    "role_play": _role_play_prompt,
    "interview": _interview_prompt,
}


def _slug(mode: ConversationMode, topic: str | None) -> str:
    """The `theme_domain` label for a moded session (OQ4)."""
    return f"{mode}: {topic}" if topic else mode


def build_mode_theme(
    config: ConversationConfig,
    *,
    level: CEFRBand,
    recent_domains: list[str],
    cooldown: int,
) -> Theme:
    """Realize a conversation config as the :class:`Theme` for the Topic block.

    ``open`` with no topic delegates to the existing cooldown-aware random pick
    (today's behaviour); ``open`` with a topic steers an open chat to it. The
    parametric modes stage their interaction around the topic (or a
    band-appropriate default when none is given) and never gate on ``level``.
    """
    mode = config.mode
    topic = config.topic
    if mode == "open":
        if topic is None:
            return get_session_theme(
                level=level, recent_domains=recent_domains, cooldown=cooldown
            )
        return Theme(domain=topic, prompt=_open_prompt(topic), target_structures=[])
    return Theme(
        domain=_slug(mode, topic),
        prompt=_MODE_PROMPTS[mode](topic),
        target_structures=list(_TARGETS.get(mode, {}).get(level, [])),
    )
