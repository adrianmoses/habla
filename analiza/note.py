"""Outputs (spec §2F): session note, append-only stats CSV, raw artifacts.

Writing into an Obsidian vault is one *layout*, not a requirement: with no
vault configured, analiza writes the same three artifacts flat under a plain
output directory. Only `output_base` knows the difference — everything below
it takes an already-resolved base directory and is layout-agnostic.
"""

import csv
import datetime as dt
from pathlib import Path

from analiza.examiner import ExaminerResult

# Used when neither a vault nor an output dir is configured. Relative, so it
# lands beside the invocation; .gitignore covers it at the repo root.
DEFAULT_OUTPUT_DIR = Path("analiza-out")

# Vault layout nests everything under this to match the Obsidian convention
# (the vault holds more than Spanish practice). A plain output dir does not.
VAULT_SUBDIR = "Español"

# Column order is the CSV contract — append-only, never reordered.
# The 90-day trend line: numbers only, never LLM prose.
# `errors_n` counts error *patterns* from examiner_v2 on (it counted rows,
# i.e. roughly occurrences, under v1) — filter on prompt_version before
# trending it across the boundary.
#
# whisper_model and prompt_version are the provenance pair: the deterministic
# metrics derived from word probabilities (fillers_n, low_conf_spans) shift
# with the whisper model, and LLM columns shift with the prompt. Neither is
# comparable across a change in its own column, so both travel with the row.
STATS_COLUMNS: list[str] = [
    "date", "ejercicio", "tema", "duration_s", "wpm_gross", "wpm_articulation",
    "pauses_n", "pause_max_s", "fillers_per_min", "connectors_unique",
    "formal_ratio", "mtld", "errors_n", "calcos_n", "score_total",
    "whisper_model", "prompt_version",
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


class OutputWriteError(Exception):
    """Could not write to the output directory, vault or not (exit code 3)."""


def _cell(text: str) -> str:
    """Make LLM-supplied text safe for a markdown table cell: a literal pipe
    or newline would otherwise split the row."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


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

        # Calques get their own section rather than a row in the errors table:
        # they are the priority category, and burying them among grammar rows
        # is what the v2 pattern grouping exists to avoid.
        lines += ["## Calcos", ""]
        if examiner.calcos:
            for e in examiner.calcos:
                lines.append(
                    f"- **{e.patron}** → {e.deberia_ser} — {e.por_que} "
                    f"({len(e.instancias)}×)"
                )
                lines += [f"    - “{i}”" for i in e.instancias]
        else:
            lines.append("_Ninguno visible en la transcripción._")
        lines.append("")

        lines += ["## Errores", ""]
        if examiner.otros_errores:
            lines += [
                "| patrón | debería ser | por qué | tipo | instancias |",
                "| --- | --- | --- | --- | --- |",
            ]
            lines += [
                f"| {_cell(e.patron)} | {_cell(e.deberia_ser)} | "
                f"{_cell(e.por_que)} | {e.tipo} | "
                f"{' · '.join(_cell(i) for i in e.instancias)} |"
                for e in examiner.otros_errores
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


def output_base(root: Path, *, vault_layout: bool) -> Path:
    """The directory the three artifacts hang off.

    The single place that knows about vault layout: `{root}/Español` for a
    vault, `{root}` for a plain output dir.
    """
    return root / VAULT_SUBDIR if vault_layout else root


def note_path(base: Path, fecha: dt.date, ejercicio: str) -> Path:
    """{base}/Sesiones/YYYY-MM-DD {ejercicio}.md, appending " (2)", " (3)", …
    on collision."""
    sesiones = base / "Sesiones"
    stem = f"{fecha.isoformat()} {ejercicio}"
    path = sesiones / f"{stem}.md"
    n = 2
    while path.exists():
        path = sesiones / f"{stem} ({n}).md"
        n += 1
    return path


def write_note(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    except OSError as e:
        raise OutputWriteError(f"failed writing {path}: {e}") from e


def append_stats_row(base: Path, row: dict[str, object]) -> None:
    """Append to {base}/analiza-stats.csv, writing the header when the file is
    created. Keys must match STATS_COLUMNS.
    """
    if set(row) != set(STATS_COLUMNS):
        raise ValueError(
            f"stats row keys {sorted(row)} != contract {sorted(STATS_COLUMNS)}"
        )
    csv_path = base / "analiza-stats.csv"
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not csv_path.exists()
        with csv_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=STATS_COLUMNS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
    except OSError as e:
        raise OutputWriteError(f"failed appending to {csv_path}: {e}") from e


def raw_dir(base: Path, fecha: dt.date, ejercicio: str) -> Path:
    """{base}/analiza-raw/YYYY-MM-DD-{ejercicio}/ — holds whisper JSON,
    metrics JSON, LLM response JSON, optional source-audio copy."""
    path = base / "analiza-raw" / f"{fecha.isoformat()}-{ejercicio}"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OutputWriteError(f"failed creating {path}: {e}") from e
    return path
