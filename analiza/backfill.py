"""Retroactive `pattern_id` assignment over stored examiner artifacts.

Sessions examined before the vocabulary (spec 034 WS1) carry no `pattern_id`,
so they are invisible to recurrence tracking. This walks the persisted
`examiner.json` files and assigns one per error row — the reprocessing the raw
artifacts exist for (`analiza` spec §2C), costing one API call per session
rather than a re-transcription.

A backfilled id is **weaker evidence than a native one**: assignment sees only
`(patron, tipo, instancias)`, not the transcript the examiner had. Each run
therefore writes a `backfill.json` sidecar recording what was assigned and
when, so WS2 can tell the two apart instead of silently mixing them.
"""

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from analiza.config import Config
from analiza.examiner import MAX_TOKENS, ExaminerError, render_vocabulario
from analiza.patrones_b2 import PatternId

# Bumped independently of the examiner prompt: this asks a different question
# (classify an existing finding) and its output is not a session score.
BACKFILL_VERSION = "backfill_v1"

_PROMPT = """\
Eres un lingüista clasificando errores ya detectados en el español de un
estudiante angloparlante. **No busques errores nuevos ni juzgues los
existentes**: cada fila ya está decidida, y tu única tarea es asignarle el
identificador del vocabulario que le corresponde.

## Vocabulario de `pattern_id`

{vocabulario}

Además existe **`otro`**, y solo ese, para lo que no encaja en ninguno.

Reglas:

- **Un fallo, un id.** Si dudas entre dos, elige el que describe la *regla*
  que el estudiante no aplicó, no el que se parece más a las palabras
  concretas.
- **El `tipo` de la fila no manda sobre el id.** Un mismo fallo puede estar
  etiquetado `calco` o `gramatica` según la sesión; elige el id por el fallo
  lingüístico que muestran las instancias.
- **`otro` es el último recurso.** Un fallo etiquetado `otro` desaparece del
  seguimiento entre sesiones, así que úsalo solo si de verdad ningún id lo
  recoge.

## Filas a clasificar

{filas}

## Formato de salida

Devuelve exactamente una asignación por fila, con el `indice` de la fila tal
como aparece arriba. No omitas ninguna ni añadas filas que no existan.
"""


class Asignacion(BaseModel):
    indice: int = Field(ge=0)
    pattern_id: PatternId


class AsignacionResult(BaseModel):
    asignaciones: list[Asignacion]


@dataclass(frozen=True)
class FileOutcome:
    path: Path
    status: str  # "assigned" | "skipped" | "failed"
    detail: str = ""
    assigned: int = 0


def find_examiner_files(base: Path) -> list[Path]:
    """Every stored examiner artifact under the resolved output base."""
    return sorted((base / "analiza-raw").glob("*/examiner.json"))


def needs_backfill(payload: dict[str, Any]) -> bool:
    """True when any error row lacks a pattern_id. A file with no errors at all
    needs nothing — there is no key to assign."""
    errores = payload.get("errores") or []
    return any("pattern_id" not in row for row in errores)


def _render_filas(errores: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{i}. tipo={row.get('tipo', '?')} · patrón: {row.get('patron', '')}\n"
        f"   instancias: {'; '.join(row.get('instancias') or []) or '(ninguna)'}"
        for i, row in enumerate(errores)
    )


def build_prompt(errores: list[dict[str, Any]]) -> str:
    prompt = _PROMPT
    for placeholder, value in [
        ("{vocabulario}", render_vocabulario()),
        ("{filas}", _render_filas(errores)),
    ]:
        prompt = prompt.replace(placeholder, value)
    return prompt


def assign(errores: list[dict[str, Any]], config: Config) -> list[PatternId]:
    """One id per row, in row order.

    Indices are validated as a permutation of range(n) rather than trusted
    positionally — a model that drops or duplicates a row would otherwise
    misalign every id after it, silently.
    """
    import anthropic

    api_key = os.environ.get(config.llm_key_env)
    if not api_key:
        raise ExaminerError(f"{config.llm_key_env} is not set")
    client = anthropic.Anthropic(api_key=api_key)

    prompt = build_prompt(errores)
    attempt_prompt = prompt
    last_error = ""
    for _ in range(2):
        try:
            response = client.messages.parse(
                model=config.llm_model,
                max_tokens=MAX_TOKENS,
                output_format=AsignacionResult,
                messages=[{"role": "user", "content": attempt_prompt}],
            )
        except anthropic.AnthropicError as e:
            raise ExaminerError(f"LLM call failed: {e}") from e
        except ValidationError as e:
            last_error = str(e)
            attempt_prompt = f"{prompt}\n\nError de validación:\n{e}\nCorrige."
            continue
        if response.parsed_output is None:
            raise ExaminerError(
                f"model returned no text block (stop_reason={response.stop_reason})"
            )
        by_index = {a.indice: a.pattern_id for a in response.parsed_output.asignaciones}
        if set(by_index) != set(range(len(errores))):
            last_error = (
                f"expected one assignment per row (indices 0..{len(errores) - 1}), "
                f"got {sorted(by_index)}"
            )
            attempt_prompt = f"{prompt}\n\n{last_error}\nCorrige."
            continue
        ids = [by_index[i] for i in range(len(errores))]
        dupes = duplicate_ids(ids)
        if dupes and attempt_prompt is prompt:
            # Two rows sharing an id means one is mis-keyed — worth one retry.
            # Unlike a live examination this is not hard-failed on the second
            # attempt: refusing to assign leaves legacy sessions invisible to
            # tracking entirely, which is worse than one imperfect id that
            # backfill.json records for review.
            attempt_prompt = (
                f"{prompt}\n\nAsignaste el mismo pattern_id a varias filas: "
                f"{dupes}. Cada fila es un fallo distinto — si de verdad son el "
                "mismo, elige para cada una el id que mejor la describa por "
                "separado.\nCorrige."
            )
            continue
        return ids
    raise ExaminerError(f"assignment failed after retry: {last_error}")


def duplicate_ids(ids: list[PatternId]) -> list[PatternId]:
    """Repeated ids, excluding `otro` (a bucket, not a fault)."""
    tracked = [p for p in ids if p != "otro"]
    return sorted({p for p in tracked if tracked.count(p) > 1})


def backfill_file(
    path: Path, config: Config, *, dry_run: bool, today: dt.date
) -> FileOutcome:
    """Assign pattern_id in place. Never partially writes: the payload is fully
    assigned in memory before either file is touched."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return FileOutcome(path, "failed", f"unreadable: {e}")

    if not isinstance(payload, dict) or not isinstance(payload.get("errores"), list):
        return FileOutcome(path, "failed", "not an examiner payload")
    if not needs_backfill(payload):
        return FileOutcome(path, "skipped", "already has pattern_id")

    errores: list[dict[str, Any]] = payload["errores"]
    try:
        ids = assign(errores, config)
    except ExaminerError as e:
        return FileOutcome(path, "failed", str(e))

    if dry_run:
        return FileOutcome(path, "assigned", "(dry run, not written)", len(ids))

    for row, pattern_id in zip(errores, ids, strict=True):
        row["pattern_id"] = pattern_id
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        (path.parent / "backfill.json").write_text(
            json.dumps(
                {
                    "backfill_version": BACKFILL_VERSION,
                    "fecha": today.isoformat(),
                    "model": config.llm_model,
                    # Non-empty means at least one id here is mis-keyed and the
                    # retry did not resolve it. Recorded rather than hidden so
                    # WS2 can discount the session and a human can review it.
                    "duplicados": duplicate_ids(ids),
                    "asignaciones": [
                        {"patron": row.get("patron", ""), "pattern_id": pid}
                        for row, pid in zip(errores, ids, strict=True)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except OSError as e:
        return FileOutcome(path, "failed", f"write failed: {e}")
    return FileOutcome(path, "assigned", "", len(ids))


def backfill_all(
    base: Path, config: Config, *, dry_run: bool, today: dt.date
) -> list[FileOutcome]:
    """Walk every stored artifact. One bad file fails that file only — a corrupt
    session must not strand the rest of the corpus unassigned."""
    return [
        backfill_file(p, config, dry_run=dry_run, today=today)
        for p in find_examiner_files(base)
    ]
