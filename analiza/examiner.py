"""LLM examiner (spec §2E): prompt build, structured-output call, one retry.

The response shape is enforced by the API (structured outputs against the
ExaminerResult schema), so this module no longer parses JSON out of prose.

Prompt contract is a versioned asset (prompts/{PROMPT_VERSION}.md); the version
is recorded in every output because prompt changes break score comparability.
Old versions are kept alongside the current one so past outputs stay readable.
"""

import importlib.resources
import json
import os
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from analiza.config import Config
from analiza.patrones_b2 import PATRONES, PatternId, Tipo

PROMPT_VERSION = "examiner_v3"

# max_tokens caps thinking AND response text together, and the examiner models
# think by default. At 4096 a 10-minute monólogo spent the entire budget
# thinking and returned zero text blocks — which surfaced as "invalid JSON"
# twice and lost the whole feedback section. Sized for a long think plus the
# full JSON payload; budget_tokens can't bound the two separately (removed on
# current models).
MAX_TOKENS = 16000

Criterio = Literal["coherencia", "fluidez", "correccion", "alcance"]

# Tipo and PatternId live in patrones_b2 (the vocabulary owns the taxonomy) and
# are re-exported here so the output schema reads in one place.
__all__ = ["ExaminerResult", "PatternId", "Tipo", "run_examiner"]


class Puntuacion(BaseModel):
    criterio: Criterio
    puntuacion: int = Field(ge=1, le=3)
    justificacion: str  # one line


class ErrorRow(BaseModel):
    """One error *pattern*, not one occurrence.

    A repeated fault (por/para, ser/estar) is a single row carrying every
    instance, so the max_length cap on `errores` budgets distinct things to
    work on rather than raw occurrences — six por/para hits no longer crowd
    out five other error types.
    """

    # The tracking key across sessions (spec 034). Enum-enforced by structured
    # outputs. `tipo` is deliberately NOT the key: the same fault has been
    # observed switching between `calco` and `gramatica` across two runs over
    # one transcript, so it is a per-session label only.
    pattern_id: PatternId
    tipo: Tipo
    patron: str  # human-readable label; the only carrier of meaning when `otro`
    deberia_ser: str
    por_que: str
    # Every occurrence, verbatim from the transcript. Uncapped: len() is the
    # severity signal that a per-instance row list threw away.
    instancias: list[str] = Field(min_length=1)


class SubjuntivoCheck(BaseModel):
    conector: str
    frase: str
    correcto: bool
    comentario: str | None = None


class Mejora(BaseModel):
    rodeo: str  # what the speaker actually said (the workaround)
    chunk_b2: str  # the B2 phrase that replaces it
    contexto: str


class ExaminerResult(BaseModel):
    puntuaciones: list[Puntuacion] = Field(min_length=4, max_length=4)
    # 10 *patterns*, not 10 occurrences — see ErrorRow.
    errores: list[ErrorRow] = Field(max_length=10)
    subjuntivo: list[SubjuntivoCheck]
    mejoras: list[Mejora] = Field(min_length=2, max_length=3)
    enfoque_proxima_sesion: str

    @model_validator(mode="after")
    def _pattern_ids_are_unique(self) -> "ExaminerResult":
        """One row per fault is the whole premise of pattern grouping, so two
        rows sharing an id means one of them is mis-keyed. Caught client-side
        (the API cannot express this), which routes it into the single retry.

        `otro` is exempt: it is a bucket, not a fault, so several unrelated
        findings legitimately land there.
        """
        tracked = [e.pattern_id for e in self.errores if e.pattern_id != "otro"]
        duplicates = sorted({p for p in tracked if tracked.count(p) > 1})
        if duplicates:
            raise ValueError(
                f"pattern_id repeated across rows: {duplicates}. Each fault gets "
                "one row; merge them or pick the id that fits each separately."
            )
        return self

    @property
    def calcos(self) -> list[ErrorRow]:
        return [e for e in self.errores if e.tipo == "calco"]

    @property
    def otros_errores(self) -> list[ErrorRow]:
        """Non-calque patterns; calques render in their own note section."""
        return [e for e in self.errores if e.tipo != "calco"]


class ExaminerError(Exception):
    """LLM call or schema validation failed after retry (exit code 4;
    the note is still written with the feedback section marked pending)."""


def load_prompt_template() -> str:
    return (
        importlib.resources.files("analiza") / "prompts" / f"{PROMPT_VERSION}.md"
    ).read_text()


def render_vocabulario() -> str:
    """The pattern vocabulary as the model sees it: id, label, wrong-form
    examples. Rendered from patrones_b2 rather than duplicated in the prompt
    asset, so the enum the API enforces and the list the model reads cannot
    drift apart."""
    return "\n".join(
        f"- `{p.id}` — {p.etiqueta}. P. ej.: {'; '.join(p.ejemplos)}"
        for p in PATRONES
    )


def build_prompt(
    transcript: str,
    metrics: dict[str, float | int],
    tema: str | None,
    ejercicio: str,
    low_conf_hints: list[tuple[float, float]],
    subjunctive_connectors: list[str],
) -> str:
    """Fill the current prompt template with this session's inputs.

    Sequential .replace(), not str.format() — the template body contains
    literal braces in the output-schema description.
    """
    hints = (
        "; ".join(f"{s:.1f}s–{e:.1f}s" for s, e in low_conf_hints)
        if low_conf_hints
        else "(ninguno)"
    )
    connectors = (
        ", ".join(subjunctive_connectors) if subjunctive_connectors else "(ninguno)"
    )
    prompt = load_prompt_template()
    for placeholder, value in [
        ("{vocabulario}", render_vocabulario()),
        ("{ejercicio}", ejercicio),
        ("{tema}", tema or "(sin tema)"),
        ("{metrics_json}", json.dumps(metrics, ensure_ascii=False)),
        ("{low_conf_hints}", hints),
        ("{subjunctive_connectors}", connectors),
        ("{transcript}", transcript),
    ]:
        prompt = prompt.replace(placeholder, value)
    return prompt


def run_examiner(prompt: str, config: Config) -> ExaminerResult:
    """Call the examiner model with structured outputs and return the result.

    `messages.parse` constrains generation to the ExaminerResult schema, so the
    *shape* — field names, types, the `tipo` enum, required keys — can no
    longer come back wrong, and neither can prose or a markdown fence wrapped
    around the JSON.

    What the API does not enforce is the count and range constraints
    (max 10 patterns, scores 1–3, 2–3 mejoras): structured outputs reject
    those, so the SDK moves each into its field's `description` — the model
    still reads them, but only pydantic enforces them, on parse, as a
    ValidationError. That is the one failure the retry below exists for.
    """
    import anthropic

    api_key = os.environ.get(config.llm_key_env)
    if not api_key:
        raise ExaminerError(f"{config.llm_key_env} is not set")
    client = anthropic.Anthropic(api_key=api_key)

    attempt_prompt = prompt
    last_error = ""
    for _ in range(2):
        try:
            response = client.messages.parse(
                model=config.llm_model,
                max_tokens=MAX_TOKENS,
                output_format=ExaminerResult,
                messages=[{"role": "user", "content": attempt_prompt}],
            )
        except anthropic.AnthropicError as e:
            raise ExaminerError(f"LLM call failed: {e}") from e
        except ValidationError as e:
            # A count/range violation, or a payload truncated mid-JSON.
            last_error = str(e)
            attempt_prompt = (
                f"{prompt}\n\nTu respuesta anterior no cumplió el esquema. "
                f"Error de validación:\n{last_error}\n"
                "Responde de nuevo únicamente con el JSON corregido."
            )
            continue
        # None means no text block at all — the model spent the whole budget
        # thinking. Retrying hits the same wall, so fail with the diagnosis.
        if response.parsed_output is None:
            raise ExaminerError(
                f"model returned no text block (stop_reason={response.stop_reason}); "
                f"raise MAX_TOKENS if this is 'max_tokens'"
            )
        return response.parsed_output
    raise ExaminerError(
        f"schema validation failed after retry (raise MAX_TOKENS if the JSON "
        f"was truncated): {last_error}"
    )
