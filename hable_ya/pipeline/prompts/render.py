"""Canonical system-prompt renderer and log_turn argument normalization.

The single source of truth for the per-band system prompt used by both the
runtime (`hable_ya.pipeline.prompts.builder`) and the fine-tune / eval
workstreams (`finetune.format`, `eval.run_eval`). Keeping these in lockstep
means any change to register guidance, FORBIDDEN phrases, or the canonical
log_turn shape lands everywhere at once.
"""

from __future__ import annotations

from typing import Any

from eval.fixtures.schema import CEFRBand, Fixture, SystemParams
from hable_ya.learner.bands import ALL_BANDS, bucket_band, is_valid_cefr_band

# Canonical log_turn argument keys (training target + runtime handler schema).
# `cefr_band` is added by spec 049 — purely prompt-engineered on the existing
# fine-tuned Gemma; not in the SFT dataset, so emission is best-effort.
CANONICAL_KEYS: tuple[str, ...] = (
    "learner_utterance",
    "errors",
    "fluency_signal",
    "L1_used",
    "cefr_band",
)
CANONICAL_ERROR_KEYS: tuple[str, ...] = ("type", "produced", "target")

# Per-band register guidance derived from eval/scoring/register.py thresholds.
# Keep numbers aligned with that module so what the model is told matches what
# the scorer actually measures.
REGISTER_GUIDANCE: dict[str, str] = {
    "A1": (
        "Very short sentences (max 10 words each). Only basic, common "
        "vocabulary. Keep words short — prefer 1-2 syllable words."
    ),
    "A2": (
        "Short sentences (max 14 words each). Everyday vocabulary; avoid "
        "long or technical words."
    ),
    "B1": (
        "Conversational sentences (max 18 words each). Common vocabulary "
        "with occasional less-frequent words."
    ),
    "B2": (
        "Natural conversational sentences (max 22 words each). Most "
        "vocabulary is fine; avoid academic or highly specialised jargon."
    ),
    "C1": (
        "Native-level register. Complex sentences are fine (max 30 words). "
        "Rich and varied vocabulary welcome."
    ),
}

# One worked recast example per band — chosen so the register of the example
# itself roughly matches the target band (so the model is not inadvertently
# primed with A1 complexity on a C1 turn).
RECAST_EXAMPLES: dict[str, tuple[str, str]] = {
    "A1": (
        "Yo es Juan.",
        "Hola Juan, yo soy María. ¿De dónde eres?",
    ),
    "A2": (
        "El parque es cerca de mi casa.",
        "Ah, el parque está cerca de tu casa. ¿Vas a menudo?",
    ),
    "B1": (
        "Ayer yo fui al cine y he visto una película muy buena.",
        "Qué bien que viste una película buena ayer. ¿De qué trataba?",
    ),
    "B2": (
        "Si tendría más tiempo, viajaría a México.",
        "Claro, si tuvieras más tiempo viajarías a México. ¿Qué región te atrae más?",
    ),
    "C1": (
        "Me molesta que siempre llega tarde a las reuniones.",
        (
            "Entiendo que te moleste que llegue tarde — es frustrante. "
            "¿Has hablado con él?"
        ),
    ),
}

# Phrases the recast scorer flags as explicit correction (eval/scoring/recast.py).
# Listed verbatim in the prompt so the model knows exactly what to avoid.
FORBIDDEN_CORRECTION_PHRASES: tuple[str, ...] = (
    "no se dice",
    "la forma correcta",
    "debes decir",
    "deberías decir",
    "se dice",
    "la palabra correcta",
    "en realidad es",
    "quieres decir",
    "quisiste decir",
    "correcto es",
)

VALID_FLUENCY_SIGNALS: tuple[str, ...] = ("weak", "moderate", "strong")

# Source of truth for the CEFR band rubric. Rendered into both
# (a) the LOG_TURN_TOOL parameter description (one-line gloss per band) and
# (b) the system prompt body (a fuller paragraph per band).
# Keeping a single constant prevents drift between the tool schema the model
# sees on parameter resolution and the rubric it sees in system context.
BAND_RUBRIC_GLOSS: dict[str, str] = {
    "A1": (
        "memorized phrases, isolated words, frequent silences; basic "
        "present tense only"
    ),
    "A2": (
        "simple sentences on familiar topics; some past forms; common "
        "vocabulary; visible effort"
    ),
    "B1": (
        "connected speech; can describe past and future; expresses "
        "opinions with some hesitation"
    ),
    "B2": (
        "detailed speech; can argue a viewpoint; subjunctive used; "
        "few grammatical lapses"
    ),
    "C1": (
        "spontaneous and fluent; idiomatic; complex grammar including "
        "hypotheticals; few errors"
    ),
}

BAND_RUBRIC_PARAGRAPH: dict[str, str] = {
    "A1": (
        "A1 — Memorized words and short formulaic phrases. Sentences "
        "rarely exceed 5–6 words. Only the present tense, and even there "
        "verbs may be conjugated incorrectly or left as infinitives. "
        "Heavy reliance on filler pauses; often answers a question with "
        "a single word or a noun phrase rather than a clause."
    ),
    "A2": (
        "A2 — Short, simple sentences about everyday topics (family, "
        "routine, immediate plans). Present tense is reliable; the "
        "preterite is attempted but often regularized incorrectly. "
        "Vocabulary is high-frequency. Discourse markers are minimal: "
        "sentences tend to be juxtaposed without connectors."
    ),
    "B1": (
        "B1 — Connected speech across a few sentences. Can narrate a "
        "past event and describe a future plan, with occasional tense "
        "confusion (preterite vs. imperfect). Uses basic connectors "
        "(porque, entonces, pero). Vocabulary is sufficient for daily "
        "life; abstract or evaluative language is still labored."
    ),
    "B2": (
        "B2 — Sustained, detailed speech on familiar and some unfamiliar "
        "topics. Argues a viewpoint with reasons. Uses the subjunctive "
        "in common contexts (creo que…, espero que…). Errors no longer "
        "obscure meaning. Rich connectors (sin embargo, aunque, "
        "mientras que); register can flex between casual and neutral."
    ),
    "C1": (
        "C1 — Spontaneous and fluent. Complex grammar including "
        "hypotheticals (si tuviera…, habría hecho…), passive and "
        "impersonal forms, varied subjunctive uses. Idiomatic phrasing. "
        "Errors are rare and do not impede comprehension. Discourse is "
        "cohesive, with self-correction and nuance."
    ),
}


def render_band_rubric_section() -> list[str]:
    """The ## Assessing the learner's level section, rendered as lines.

    Used by render_system_prompt; co-located so test byte-identity checks
    can import the same source.
    """
    lines: list[str] = [
        "## Assessing the learner's level",
        "On every turn, classify the learner's last utterance into a CEFR "
        "band (A1, A2, B1, B2, or C1) using the rubric below, and emit "
        "your read in the `cefr_band` field of `log_turn`. Base the read "
        "on the learner's production characteristics (sentence "
        "complexity, tense usage, vocabulary range, discourse), not on "
        "the topic of the conversation.",
        "",
    ]
    for band in ALL_BANDS:
        lines.append(BAND_RUBRIC_PARAGRAPH[band])
        lines.append("")
    return lines


def band_from_production_level(level: float) -> CEFRBand:
    """Backwards-compatible wrapper around the shared bucketing rule."""
    return bucket_band(level)


def render_system_prompt(
    params: SystemParams,
    band: CEFRBand | None = None,
) -> str:
    """Build the runtime/fine-tune system prompt from fixture system_params.

    ``band`` overrides the production-level-derived band. Pass
    ``fixture.metadata.cefr_band`` when available so the prompt's register
    guidance matches what the scorer actually grades against.
    """
    p = params.profile
    t = params.theme
    if band is None:
        band = band_from_production_level(p.production_level)

    lines: list[str] = [
        "You are a Spanish conversation partner for a language learner.",
        "",
        "## Learner",
        f"- CEFR level: {band}",
        f"- L1 reliance: {p.L1_reliance:.2f} "
        "(higher = more likely to fall back on English)",
        f"- Speech fluency: {p.speech_fluency:.2f}",
    ]
    if p.error_patterns:
        lines.append(f"- Known error patterns: {', '.join(p.error_patterns)}")
    if p.vocab_strengths:
        lines.append(f"- Vocabulary strengths: {', '.join(p.vocab_strengths)}")

    lines.extend(
        [
            "",
            f"## Topic: {t.domain}",
            t.prompt,
        ]
    )
    if t.target_structures:
        lines.append(f"Target structures: {', '.join(t.target_structures)}.")

    lines.extend(
        [
            "",
            "## Response format (strict)",
            "- 1 to 3 sentences total.",
            "- Exactly one question mark.",
            "- Spanish only. Do not use any English words — not even "
            '"sorry", "yes", "no", "I", "ok".',
            f"- {band} register: {REGISTER_GUIDANCE[band]}",
            "",
        ]
    )
    lines.extend(render_band_rubric_section())
    lines.extend(
        [
            "## Handling learner errors: recast, never correct",
            "If the learner's last turn contains an error, include the CORRECT "
            "form naturally in your reply — as if paraphrasing what they meant. "
            "Do not mention that anything was wrong.",
            "",
            "Never use any of these phrases (they count as explicit correction):",
        ]
    )
    for phrase in FORBIDDEN_CORRECTION_PHRASES:
        lines.append(f'  "{phrase}"')
    lines.append("Also never use the Spanish word 'error' when talking to the learner.")

    lines.extend(
        [
            "",
            "Never echo the learner's incorrect form. If you need to refer "
            "back to what they said, use the corrected version.",
            "",
            "### Example",
        ]
    )
    learner_ex, assistant_ex = RECAST_EXAMPLES[band]
    lines.extend(
        [
            f'Learner: "{learner_ex}"',
            f'You: "{assistant_ex}"',
            "",
            "## After your reply, call log_turn",
            "After your Spanish reply, emit the tool call on its own line in "
            "this EXACT format — no code fences, no other wrappers:",
            "",
            'log_turn({"learner_utterance": "...", "errors": [...], '
            '"fluency_signal": "...", "L1_used": ..., "cefr_band": "..."})',
            "",
            "Use that exact function-call shape: the literal name `log_turn`, "
            "an opening paren, a single JSON object, a closing paren. Do not "
            "wrap it in code fences or add `<tool_call>` tags.",
            "",
            "Arguments (all required):",
            "- learner_utterance: the learner's last message copied VERBATIM.",
            "- errors: list of {type, produced, target} objects. "
            '"type" is the error category (e.g. "ser_estar"); '
            '"produced" is the wrong form the learner used; '
            '"target" is the corrected form you wove into your reply. '
            "Use [] if there were no errors.",
            '- fluency_signal: "weak", "moderate", or "strong" — based on the '
            "learner's last message (hesitations, fragments, short utterances → "
            "weak; complete sentences with some errors → moderate; fluent and "
            "extended → strong).",
            "- L1_used: true if the learner's last message contained any "
            "English word, otherwise false.",
            '- cefr_band: "A1", "A2", "B1", "B2", or "C1" — your read of the '
            "learner's last utterance against the rubric above. Base on "
            "production characteristics, not topic.",
            "",
            "### Full-turn example",
            f'Learner: "{learner_ex}"',
            "You:",
            assistant_ex,
            'log_turn({"learner_utterance": "'
            + learner_ex
            + '", "errors": [], "fluency_signal": "moderate", '
            f'"L1_used": false, "cefr_band": "{band}"}})',
        ]
    )

    return "\n".join(lines)


def normalize_error_item(
    raw: Any, fallback_type: str | None = None
) -> dict[str, str] | None:
    """Coerce any fixture/runtime error entry into {type, produced, target}.

    Accepts dicts with assorted key names, or strings (e.g. ``"ser_estar"`` or
    ``"vowel_substitution:levento"``). Returns ``None`` if nothing usable.
    """
    if isinstance(raw, dict):
        err_type = (
            raw.get("type")
            or raw.get("pattern")
            or raw.get("error_type")
            or fallback_type
            or ""
        )
        produced = raw.get("produced") or raw.get("error_form") or raw.get("form") or ""
        target = (
            raw.get("target") or raw.get("correct_form") or raw.get("correction") or ""
        )
        if not err_type and not produced:
            return None
        return {
            "type": str(err_type),
            "produced": str(produced),
            "target": str(target),
        }

    if isinstance(raw, str):
        if ":" in raw:
            err_type, produced = raw.split(":", 1)
            return {
                "type": err_type.strip(),
                "produced": produced.strip(),
                "target": "",
            }
        return {"type": raw.strip(), "produced": "", "target": ""}

    return None


def _last_user_utterance(fixture: Fixture) -> str:
    for turn in reversed(fixture.conversation):
        if turn.role == "user":
            return turn.content
    return ""


def normalize_log_turn_args(
    fixture: Fixture, raw_args: dict[str, Any]
) -> dict[str, Any]:
    """Fixture-aware canonical ``log_turn`` payload.

    Prefers structured data from ``raw_args`` when present; otherwise falls back
    to ``fixture.metadata`` (errors_present, fluency_signal, L1_used).

    For runtime (no fixture), use :func:`normalize_runtime_log_turn_args`.
    """
    # Anchor on the conversation's last user turn — that's the source of truth
    # for ``eval/scoring/turn.py`` (tool_args_correct requires exact match).
    utterance = _last_user_utterance(fixture) or raw_args.get("learner_utterance", "")

    source_errors: list[Any] = []
    for key in ("errors", "errors_observed", "errors_detected"):
        val = raw_args.get(key)
        if isinstance(val, list) and val:
            source_errors = val
            break

    meta_types = list(fixture.metadata.errors_present)
    errors: list[dict[str, str]] = []
    for idx, item in enumerate(source_errors):
        fallback_type = meta_types[idx] if idx < len(meta_types) else None
        norm = normalize_error_item(item, fallback_type=fallback_type)
        if norm is not None:
            errors.append(norm)

    return {
        "learner_utterance": utterance,
        "errors": errors,
        "fluency_signal": fixture.metadata.fluency_signal,
        "L1_used": fixture.metadata.L1_used,
    }


def normalize_runtime_log_turn_args(
    raw_args: dict[str, Any],
) -> dict[str, Any] | None:
    """Normalize a runtime-emitted ``log_turn`` payload with no fixture context.

    Returns the canonical 5-key dict, or ``None`` if ``raw_args`` is
    fundamentally malformed in the four core fields (errors not a list,
    fluency_signal not in the valid enum, L1_used not coercible to bool).

    ``cefr_band`` is best-effort: missing or out-of-enum maps to ``None`` so
    the rest of the observation still flows. The caller is expected to
    surface a counter on the missing path (see ``HableYaToolHandler``).
    """
    utterance = raw_args.get("learner_utterance", "")
    if not isinstance(utterance, str) or not utterance.strip():
        return None

    raw_errors = raw_args.get("errors", [])
    if not isinstance(raw_errors, list):
        return None
    errors: list[dict[str, str]] = []
    for item in raw_errors:
        norm = normalize_error_item(item)
        if norm is not None:
            errors.append(norm)

    fluency = raw_args.get("fluency_signal", "moderate")
    if fluency not in VALID_FLUENCY_SIGNALS:
        return None

    l1_raw = raw_args.get("L1_used", False)
    if isinstance(l1_raw, bool):
        l1_used = l1_raw
    elif isinstance(l1_raw, (int, float)):
        l1_used = bool(l1_raw)
    elif isinstance(l1_raw, str):
        l1_used = l1_raw.strip().lower() in ("true", "1", "yes")
    else:
        return None

    band_raw = raw_args.get("cefr_band")
    cefr_band = band_raw if is_valid_cefr_band(band_raw) else None

    return {
        "learner_utterance": utterance,
        "errors": errors,
        "fluency_signal": fluency,
        "L1_used": l1_used,
        "cefr_band": cefr_band,
    }
