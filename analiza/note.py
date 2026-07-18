"""Outputs (spec §2F): Obsidian session note, append-only stats CSV, raw artifacts."""

import datetime as dt
from pathlib import Path

from analiza.examiner import ExaminerResult

# Column order is the CSV contract — append-only, never reordered.
# The 90-day trend line: numbers only, never LLM prose.
STATS_COLUMNS: list[str] = [
    "date", "ejercicio", "tema", "duration_s", "wpm_gross", "wpm_articulation",
    "pauses_n", "pause_max_s", "fillers_per_min", "connectors_unique",
    "formal_ratio", "mtld", "errors_n", "score_total", "prompt_version",
]


class VaultWriteError(Exception):
    """Could not write into the vault (exit code 3)."""


def render_note(
    fecha: dt.date,
    ejercicio: str,
    tema: str | None,
    duration_s: float,
    metrics: dict[str, float | int],
    examiner: ExaminerResult | None,  # None → "feedback pendiente" section
    prompt_version: str,
) -> str:
    """Render the session note markdown.

    Frontmatter per vault convention: type: sesion, ejercicio, fecha,
    duracion (minutes), tema, fuente: analiza. Body: metrics summary block
    (fillers labeled as floors), examiner scores, error table in vault table
    format, upgrade suggestions as `frase :: contexto` bullets under
    "Chunks capturados" so the weekly-review promotion flow applies unchanged.

    TODO(implement).
    """
    raise NotImplementedError


def note_path(vault: Path, fecha: dt.date, ejercicio: str) -> Path:
    """{vault}/Español/Sesiones/YYYY-MM-DD {ejercicio}.md, appending " (2)",
    " (3)", … on collision."""
    raise NotImplementedError


def write_note(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    except OSError as e:
        raise VaultWriteError(f"failed writing {path}: {e}") from e


def append_stats_row(vault: Path, row: dict[str, object]) -> None:
    """Append to {vault}/Español/analiza-stats.csv, writing the header when
    the file is created. Keys must match STATS_COLUMNS.

    TODO(implement).
    """
    raise NotImplementedError


def raw_dir(vault: Path, fecha: dt.date, ejercicio: str) -> Path:
    """{vault}/Español/analiza-raw/YYYY-MM-DD-{ejercicio}/ — holds whisper
    JSON, metrics JSON, LLM response JSON, optional source-audio copy."""
    raise NotImplementedError
