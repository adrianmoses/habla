"""LLM examiner (spec §2E): prompt build, call, schema validation, one retry.

Prompt contract is a versioned asset (prompts/examiner_v1.md); the version is
recorded in every output because prompt changes break score comparability.
"""

import importlib.resources
import json
import os
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

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
        ("{ejercicio}", ejercicio),
        ("{tema}", tema or "(sin tema)"),
        ("{metrics_json}", json.dumps(metrics, ensure_ascii=False)),
        ("{low_conf_hints}", hints),
        ("{subjunctive_connectors}", connectors),
        ("{transcript}", transcript),
    ]:
        prompt = prompt.replace(placeholder, value)
    return prompt


def _extract_json(text: str) -> str:
    """Tolerate a fenced code block around the JSON, nothing more."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return fenced.group(1).strip() if fenced else text.strip()


def run_examiner(prompt: str, config: Config) -> ExaminerResult:
    """Call the examiner model and validate against ExaminerResult.

    On a schema violation: one retry with the validation error appended to the
    prompt; on second failure raise ExaminerError.
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
            response = client.messages.create(
                model=config.llm_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": attempt_prompt}],
            )
        except anthropic.AnthropicError as e:
            raise ExaminerError(f"LLM call failed: {e}") from e
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        try:
            return ExaminerResult.model_validate_json(_extract_json(text))
        except (ValidationError, ValueError) as e:
            last_error = str(e)
            attempt_prompt = (
                f"{prompt}\n\nTu respuesta anterior no cumplió el esquema. "
                f"Error de validación:\n{last_error}\n"
                "Responde de nuevo únicamente con el JSON corregido."
            )
    raise ExaminerError(f"schema validation failed after retry: {last_error}")
