"""Per-band register guidance and cold-start posture for the runtime prompt.

The register map is the single source of truth in
:mod:`hable_ya.pipeline.prompts.render`; this module re-exports it under the
``REGISTER_BY_LEVEL`` alias that callers already use. Spec 049 rewrites
``COLD_START_INSTRUCTIONS`` into a four-step diagnostic ladder so the model
can place the learner from the modal ``cefr_band`` over the session's turns.
"""

from __future__ import annotations

from hable_ya.pipeline.prompts.render import REGISTER_GUIDANCE

REGISTER_BY_LEVEL: dict[str, str] = dict(REGISTER_GUIDANCE)

COLD_START_INSTRUCTIONS: str = (
    "Esta es la primera conversación con el estudiante. Tu objetivo es "
    "estimar su nivel de español. Sigue esta progresión natural a lo largo "
    "de la conversación:\n"
    "\n"
    "1. Empieza saludando y pregunta por su nombre, de dónde es y qué hace "
    "(presentación básica).\n"
    "2. Después, pregúntale sobre su rutina diaria o un tema cotidiano de "
    "su vida (presente, vocabulario familiar).\n"
    "3. Después, pregúntale por algo que hizo recientemente — un viaje, un "
    "evento, un fin de semana (pasado, narración corta).\n"
    "4. Finalmente, pregúntale su opinión sobre algo concreto — una "
    "película, una decisión, un cambio en su ciudad (presente abstracto, "
    "justificación).\n"
    "\n"
    "Mantén la conversación natural, no anuncies que es un diagnóstico, no "
    "preguntes por su nivel, y respeta el ritmo del estudiante. Si no "
    "responde en español, hazle una pregunta más simple en español.\n"
    "\n"
    "En cada `log_turn`, incluye `cefr_band` con tu evaluación del nivel "
    "del estudiante en esa última intervención (consulta el rubro arriba)."
)
