"""Narrative pass over an aggregation (spec 034 WS3).

Mirrors `examiner.py` — versioned prompt asset, structured outputs, one retry
for the constraints the API cannot express — but the input is `ProgresoStats`,
never a transcript and never a raw `examiner.json`. That split is the governing
principle of the whole track (`analiza` spec §5): counting is deterministic and
reproducible, narration is not, and narration must never be load-bearing for a
number.

So the model gets numbers that were already counted and one job: judgment about
which of them matter. Two guards keep it there —

· it cites faults by `pattern_id`, and an id the aggregation never saw is a
  hallucination that fails the response (`uncited_patterns`), because the whole
  value of a "focus next" line is that it points at something real;
· the note renders each cited id's label from the vocabulary rather than from
  the model's prose, so a fault cannot be quietly renamed on its way to the
  page.

`ExaminerError` and `MAX_TOKENS` are reused rather than redeclared, following
`backfill.py`: it is the same failure class (an LLM call that produced no usable
structured result) and the same sizing lesson (max_tokens caps thinking and text
together, and these models think by default).
"""

import importlib.resources

from pydantic import BaseModel, Field, ValidationError

from analiza.config import Config
from analiza.examiner import MAX_TOKENS, ExaminerError
from analiza.patrones_b2 import PatternId
from analiza.progreso import ProgresoStats

PROMPT_VERSION = "progreso_v1"

__all__ = [
    "MAX_TOKENS",
    "PROMPT_VERSION",
    "ExaminerError",
    "ProgresoResult",
    "build_prompt",
    "run_progreso",
    "uncited_patterns",
]


class PatronPrioritario(BaseModel):
    """One fault worth working on next, keyed rather than described.

    `pattern_id` is the tracking key, so the note can render the vocabulary's
    own label and the learner can follow the same fault to the next report.
    """

    pattern_id: PatternId
    por_que: str  # one line, grounded in the counts


class ProgresoResult(BaseModel):
    lectura: str  # what moved and what did not
    # No minimum: a corpus of unexamined sessions has no patterns to prioritise,
    # and forcing a row there would be an invitation to invent one.
    patrones_prioritarios: list[PatronPrioritario] = Field(max_length=3)
    # What the data cannot say — truncated sessions, low-confidence recordings,
    # windows too short to read. Its own field rather than a hedge buried in
    # the prose, because it is the part a learner most needs to see.
    cautelas: list[str]
    enfoque_proxima_sesion: str


def load_prompt_template() -> str:
    return (
        importlib.resources.files("analiza") / "prompts" / f"{PROMPT_VERSION}.md"
    ).read_text()


def build_prompt(stats: ProgresoStats) -> str:
    """Fill the template with the serialised aggregation.

    Sequential .replace(), not str.format() — the template body contains
    literal braces in the output-schema description.
    """
    return load_prompt_template().replace(
        "{stats_json}", stats.model_dump_json(indent=2)
    )


def uncited_patterns(result: ProgresoResult, stats: ProgresoStats) -> list[PatternId]:
    """Ids the narrative cites that the aggregation never recorded.

    The enum stops the model inventing an id that does not exist in the
    vocabulary; it cannot stop it citing a real id this learner has never
    produced. Only the aggregation knows that, so the check lives here and
    routes into the retry.
    """
    conocidos = {r.pattern_id for r in stats.patrones}
    citados = {p.pattern_id for p in result.patrones_prioritarios}
    return sorted(citados - conocidos)


def run_progreso(stats: ProgresoStats, config: Config) -> ProgresoResult:
    """Call the model with the aggregation and return its reading.

    Same shape as `run_examiner`: `messages.parse` constrains generation to the
    schema, so field names, types and the `pattern_id` enum cannot come back
    wrong. What the API does not enforce — the 3-item cap, and every citation
    pointing at a fault this learner actually produced — is checked here, and
    that is what the single retry exists for.
    """
    import os

    import anthropic

    api_key = os.environ.get(config.llm_key_env)
    if not api_key:
        raise ExaminerError(f"{config.llm_key_env} is not set")
    client = anthropic.Anthropic(api_key=api_key)

    prompt = build_prompt(stats)
    attempt_prompt = prompt
    last_error = ""
    for _ in range(2):
        try:
            response = client.messages.parse(
                model=config.llm_model,
                max_tokens=MAX_TOKENS,
                output_format=ProgresoResult,
                messages=[{"role": "user", "content": attempt_prompt}],
            )
        except anthropic.AnthropicError as e:
            raise ExaminerError(f"LLM call failed: {e}") from e
        except ValidationError as e:
            last_error = str(e)
            attempt_prompt = (
                f"{prompt}\n\nTu respuesta anterior no cumplió el esquema. "
                f"Error de validación:\n{last_error}\n"
                "Responde de nuevo únicamente con el JSON corregido."
            )
            continue
        # None means no text block at all — the whole budget went to thinking.
        # Retrying hits the same wall, so fail with the diagnosis.
        if response.parsed_output is None:
            raise ExaminerError(
                f"model returned no text block (stop_reason={response.stop_reason}); "
                f"raise MAX_TOKENS if this is 'max_tokens'"
            )
        inventados = uncited_patterns(response.parsed_output, stats)
        if not inventados:
            return response.parsed_output
        last_error = (
            f"citaste pattern_id que no aparecen en la agregación: {inventados}"
        )
        attempt_prompt = (
            f"{prompt}\n\n{last_error}. Solo puedes priorizar patrones que "
            "estén en `patrones`; si ninguno merece prioridad, devuelve la "
            "lista vacía.\nCorrige."
        )
    raise ExaminerError(f"narrative failed after retry: {last_error}")
