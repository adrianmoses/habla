"""Shared variance helpers for prompt builders.

Phase 3 of the fixture generation plan: each builder samples three axes
(difficulty / fluency_signal / prior_turn_count) per fixture, plus picks a
surface-form realisation for the target error from a small per-type catalogue.
Lets the generator produce hundreds of structurally-distinct prompts per
(band, error) combo instead of cycling ~40 unique strings.

Sampling is seeded from (band, index, salt) so a given build is reproducible.
"""

from __future__ import annotations

import random
from typing import Final

from eval.fixtures.schema import CEFRBand

# Per-error-type surface-form catalogue. Keeps `ser_estar` from always
# producing "está cerca". Each entry is a one-line description of a distinct
# realisation the generator can target.
SURFACE_FORMS: Final[dict[str, list[str]]] = {
    "ser_estar": [
        "location ('la casa es cerca' → 'está cerca')",
        "temporary state ('soy cansado' → 'estoy cansado')",
        "passing emotion ('soy feliz hoy' → 'estoy feliz hoy')",
        "profession ('estoy profesor' → 'soy profesor')",
        "weather ('es nublado' → 'está nublado')",
    ],
    "gender_agreement": [
        "noun + adjective ('el casa rojo' → 'la casa roja')",
        "article gender ('el agua frío' → 'el agua fría')",
        "feminine noun with masculine article ('un mano' → 'una mano')",
        "irregular gender ('la problema' → 'el problema')",
    ],
    "missing_article": [
        "definite article on subject ('Hermano se llama Carlos')",
        "indefinite article in possession ('Tengo perro')",
        "article on body part ('Me duele cabeza')",
    ],
    "verb_conjugation": [
        "1st-person -ar verb ('yo trabaja' → 'yo trabajo')",
        "tu form of irregular verb ('tu tiene' → 'tienes')",
        "stem-changing verb ('yo dormo' → 'duermo')",
        "3rd-person plural mismatch ('ellos come' → 'comen')",
    ],
    "preterite_imperfect": [
        "habitual past as preterite ('ayer comí siempre' → 'comía siempre')",
        "single completed action as imperfect ('cuando llegaba ayer' → 'cuando llegué')",
        "background description as preterite ('cuando fui niño jugué' → 'cuando era niño jugaba')",
    ],
    "subjunctive_avoidance": [
        "indicative after 'quiero que' ('quiero que viene' → 'venga')",
        "indicative after 'es importante que' ('es importante que estudia' → 'estudie')",
        "indicative after recommendation ('te recomiendo que vas' → 'vayas')",
    ],
    "subjunctive": [
        "subjunctive after 'aunque' (concessive)",
        "subjunctive in adjective clauses ('busco un libro que es' → 'que sea')",
        "subjunctive after 'para que'",
        "subjunctive after expressions of doubt ('dudo que está' → 'que esté')",
    ],
    "por_para": [
        "por for purpose ('estudio por aprender' → 'para aprender')",
        "para for duration ('estudié para dos horas' → 'durante dos horas')",
        "por for destination ('voy por casa' → 'a casa')",
        "para for cause ('gracias para venir' → 'por venir')",
    ],
    "register_slip": [
        "informal vocabulary in formal context ('chévere' in business setting)",
        "tu/usted slippage ('tu deberías' addressing a stranger)",
        "anglicism in formal context ('hacer un meeting')",
        "academic register too low ('súper bueno' in essay)",
    ],
    "idiomatic_error": [
        "literal translation of English idiom ('tomé ventaja de' → 'aproveché')",
        "wrong collocation ('hacer una decisión' → 'tomar una decisión')",
        "calqued phrase ('poner nuestras cabezas juntas' → 'poner la cabeza en común')",
        "anglicized verb usage ('aplicar para un trabajo' → 'solicitar')",
    ],
}

DIFFICULTIES: Final[tuple[tuple[str, float], ...]] = (
    ("straightforward", 0.7),
    ("ambiguous", 0.3),
)
FLUENCY_SIGNALS: Final[tuple[str, ...]] = ("weak", "moderate", "strong")
PRIOR_TURN_COUNTS: Final[tuple[int, ...]] = (1, 2)


def _rng(band: CEFRBand, idx: int, salt: str = "") -> random.Random:
    return random.Random(f"{band}:{idx}:{salt}")


def sample_axes(band: CEFRBand, idx: int, salt: str = "") -> tuple[str, str, int]:
    """Return (difficulty, fluency_signal, prior_turn_count) for fixture #idx."""
    rng = _rng(band, idx, salt)
    difficulty = rng.choices(
        [d for d, _ in DIFFICULTIES],
        weights=[w for _, w in DIFFICULTIES],
    )[0]
    fluency = rng.choice(FLUENCY_SIGNALS)
    turn_count = rng.choice(PRIOR_TURN_COUNTS)
    return difficulty, fluency, turn_count


def pick_surface_form(error_type: str, band: CEFRBand, idx: int) -> str:
    """Pick one surface-form example for ``error_type``. Empty if unknown."""
    forms = SURFACE_FORMS.get(error_type, [])
    if not forms:
        return ""
    return _rng(band, idx, error_type).choice(forms)


def render_axes_block(difficulty: str, fluency: str, turn_count: int) -> str:
    """Format the variance axes as a prompt fragment for the generator."""
    return (
        "Variance constraints (use these EXACT values):\n"
        f"- Difficulty: **{difficulty}** — set `metadata.difficulty` to this.\n"
        f"- Fluency signal: **{fluency}** — set `metadata.fluency_signal` and "
        f"`log_turn.arguments.fluency_signal` to this. Phrase the learner "
        f"utterance accordingly (weak = hesitations, fragments, very short; "
        f"moderate = complete sentences with errors; strong = fluent and extended).\n"
        f"- Prior assistant turns: **{turn_count}** assistant turn(s) before "
        "the final learner utterance."
    )
