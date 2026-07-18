"""LLM examiner (spec §2E): prompt build, call, schema validation, one retry.

Prompt contract is a versioned asset (prompts/examiner_v1.md); the version is
recorded in every output because prompt changes break score comparability.
"""

import importlib.resources
from typing import Literal

from pydantic import BaseModel, Field

from analiza.config import Config

PROMPT_VERSION = "examiner_v1"

Criterio = Literal["coherencia", "fluidez", "correccion", "alcance"]


class Puntuacion(BaseModel):
    criterio: Criterio
    puntuacion: int = Field(ge=1, le=3)
    justificacion: str  # one line


class ErrorRow(BaseModel):
    dije: str
    deberia_ser: str
    por_que: str


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
    errores: list[ErrorRow] = Field(max_length=10)
    subjuntivo: list[SubjuntivoCheck]
    mejoras: list[Mejora] = Field(min_length=2, max_length=3)
    enfoque_proxima_sesion: str


class ExaminerError(Exception):
    """LLM call or schema validation failed after retry (exit code 4;
    the note is still written with the feedback section marked pending)."""


def load_prompt_template() -> str:
    return (
        importlib.resources.files("analiza") / "prompts" / f"{PROMPT_VERSION}.md"
    ).read_text()


def build_prompt(
    transcript: str,
    metrics: dict[str, float | int],
    tema: str | None,
    ejercicio: str,
    low_conf_hints: list[tuple[float, float]],
    subjunctive_connectors: list[str],
) -> str:
    """Fill the examiner_v1.md template with this session's inputs.

    TODO(implement): simple .format()/replace on the template placeholders.
    """
    raise NotImplementedError


def run_examiner(prompt: str, config: Config) -> ExaminerResult:
    """Call the examiner model and validate against ExaminerResult.

    On a schema violation: one retry with the validation error appended to the
    prompt; on second failure raise ExaminerError.

    TODO(implement): anthropic SDK call using config.llm_model, key from
    config.llm_key_env.
    """
    raise NotImplementedError
