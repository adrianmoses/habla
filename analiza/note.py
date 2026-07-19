"""Outputs (spec §2F): Obsidian session note, append-only stats CSV, raw artifacts."""

import csv
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

# Metric key → display label for the note's summary block.
_METRIC_LABELS: list[tuple[str, str]] = [
    ("wpm_gross", "WPM (bruto)"),
    ("wpm_articulation", "WPM (articulación)"),
    ("speech_time_s", "Tiempo de habla (s)"),
    ("pauses_n", "Pausas"),
    ("pauses_total_s", "Pausas total (s)"),
    ("pause_max_s", "Pausa máx (s)"),
    ("pauses_midclause_n", "Pausas mid-clause"),
    ("fillers_n", "Muletillas (cota inferior)"),
    ("fillers_per_min", "Muletillas/min (cota inferior)"),
    ("connectors_unique_n", "Conectores únicos"),
    ("connectors_formal_ratio", "Ratio formal"),
    ("ttr", "TTR"),
    ("mtld", "MTLD"),
    ("repeats_n", "Repeticiones"),
    ("vad_transcript_gap_s", "Hueco VAD↔transcripción (s)"),
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
    """Render the session note markdown (frontmatter + metrics + feedback)."""
    lines = [
        "---",
        "type: sesion",
        f"ejercicio: {ejercicio}",
        f"fecha: {fecha.isoformat()}",
        f"duracion: {duration_s / 60:.1f}",
        f"tema: {tema or ''}",
        "fuente: analiza",
        "---",
        "",
        "## Métricas",
        "",
        "Las muletillas están subestimadas (Whisper las suprime): la cifra es "
        "una cota inferior, solo la tendencia es significativa.",
        "",
    ]
    lines += [
        f"- {label}: {metrics[key]}" for key, label in _METRIC_LABELS if key in metrics
    ]
    lines.append("")

    if examiner is None:
        lines += [
            "## Feedback del examinador",
            "",
            "_Pendiente: el pase LLM falló o se omitió (--no-llm). "
            "Reintenta con los artefactos crudos._",
            "",
        ]
    else:
        lines += ["## Feedback del examinador", ""]
        lines += [
            f"- **{p.criterio}**: {p.puntuacion}/3 — {p.justificacion}"
            for p in examiner.puntuaciones
        ]
        total = sum(p.puntuacion for p in examiner.puntuaciones)
        lines += ["", f"**Total: {total}/12**", ""]

        lines += ["## Errores", ""]
        if examiner.errores:
            lines += [
                "| dije | debería ser | por qué |",
                "| --- | --- | --- |",
            ]
            lines += [
                f"| {e.dije} | {e.deberia_ser} | {e.por_que} |"
                for e in examiner.errores
            ]
        else:
            lines.append("_Ninguno visible en la transcripción._")
        lines.append("")

        if examiner.subjuntivo:
            lines += ["## Subjuntivo", ""]
            for s in examiner.subjuntivo:
                verdict = "✅" if s.correcto else "❌"
                comment = f" — {s.comentario}" if s.comentario else ""
                lines.append(f"- {verdict} **{s.conector}**: “{s.frase}”{comment}")
            lines.append("")

        lines += ["## Chunks capturados", ""]
        lines += [
            f"- {m.chunk_b2} :: {m.contexto} (en vez de: “{m.rodeo}”)"
            for m in examiner.mejoras
        ]
        lines += [
            "",
            "## Enfoque próxima sesión",
            "",
            examiner.enfoque_proxima_sesion,
            "",
        ]

    lines += [f"_prompt_version: {prompt_version}_", ""]
    return "\n".join(lines)


def note_path(vault: Path, fecha: dt.date, ejercicio: str) -> Path:
    """{vault}/Español/Sesiones/YYYY-MM-DD {ejercicio}.md, appending " (2)",
    " (3)", … on collision."""
    sesiones = vault / "Español" / "Sesiones"
    base = f"{fecha.isoformat()} {ejercicio}"
    path = sesiones / f"{base}.md"
    n = 2
    while path.exists():
        path = sesiones / f"{base} ({n}).md"
        n += 1
    return path


def write_note(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    except OSError as e:
        raise VaultWriteError(f"failed writing {path}: {e}") from e


def append_stats_row(vault: Path, row: dict[str, object]) -> None:
    """Append to {vault}/Español/analiza-stats.csv, writing the header when
    the file is created. Keys must match STATS_COLUMNS.
    """
    if set(row) != set(STATS_COLUMNS):
        raise ValueError(
            f"stats row keys {sorted(row)} != contract {sorted(STATS_COLUMNS)}"
        )
    csv_path = vault / "Español" / "analiza-stats.csv"
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not csv_path.exists()
        with csv_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=STATS_COLUMNS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
    except OSError as e:
        raise VaultWriteError(f"failed appending to {csv_path}: {e}") from e


def raw_dir(vault: Path, fecha: dt.date, ejercicio: str) -> Path:
    """{vault}/Español/analiza-raw/YYYY-MM-DD-{ejercicio}/ — holds whisper
    JSON, metrics JSON, LLM response JSON, optional source-audio copy."""
    path = vault / "Español" / "analiza-raw" / f"{fecha.isoformat()}-{ejercicio}"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise VaultWriteError(f"failed creating {path}: {e}") from e
    return path
