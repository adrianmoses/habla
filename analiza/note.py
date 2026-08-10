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
from analiza.progreso import (
    PatronRecurrencia,
    ProgresoStats,
    TendenciaMetrica,
    plural,
)

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
# whisper_model, prompt_version and vocab_version are the provenance trio: the
# deterministic metrics derived from word probabilities (fillers_n,
# low_conf_spans) shift with the whisper model, LLM columns shift with the
# prompt, and which pattern_ids a session *could* have reported shifts with the
# vocabulary. Nothing is comparable across a change in its own column, so all
# three travel with the row.
STATS_COLUMNS: list[str] = [
    "date", "ejercicio", "tema", "duration_s", "wpm_gross", "wpm_articulation",
    "pauses_n", "pause_max_s", "fillers_per_min", "connectors_unique",
    "formal_ratio", "mtld", "errors_n", "calcos_n", "score_total",
    "whisper_model", "prompt_version", "vocab_version",
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


def _num(value: float) -> str:
    """Trim a float so a table of means reads as numbers rather than noise."""
    return f"{value:g}"


def _estado_patron(p: PatronRecurrencia) -> str:
    """The recurrence verdict as an *observation* (spec 034 OQ2).

    Never "resuelto": the report says how long a fault has gone unseen and how
    much of that silence is worth; deciding it is fixed is the learner's call.
    """
    if p.estado == "ausente":
        return "sin aparecer en " + plural(
            p.ausencias_concluyentes, "sesión", "sesiones"
        )
    if p.estado == "no-concluyente":
        return (
            "sin aparecer en "
            + plural(p.sesiones_desde_ultima, "sesión", "sesiones")
            + ", pero ninguna lo descarta"
        )
    if p.sesiones_desde_ultima == 0:
        return "en la última sesión"
    return "visto hace " + plural(p.sesiones_desde_ultima, "sesión", "sesiones")


def _tendencias_lines(tendencias: list[TendenciaMetrica], ventana_n: int) -> list[str]:
    lines = [
        f"| métrica | primeras {ventana_n} | últimas {ventana_n} | Δ |",
        "| --- | --- | --- | --- |",
    ]
    for t in tendencias:
        if t.estado == "ok" and t.primeras and t.ultimas and t.delta is not None:
            lines.append(
                f"| {t.etiqueta} | {_num(t.primeras.media)} | "
                f"{_num(t.ultimas.media)} | {t.delta:+g} |"
            )
        else:
            lines.append(
                f"| {t.etiqueta} | — | — | insuficiente "
                f"({plural(t.sesiones_n, 'sesión', 'sesiones')}, "
                f"faltan {t.faltan}) |"
            )
    return lines


def render_progreso_note(
    stats: ProgresoStats,
    narrativa: str | None = None,  # None → numbers only (--no-llm or gated)
) -> str:
    """Render the progress note: scope, per-segment trends, recurrence.

    Every number here comes from `stats` and nothing is recomputed — the note
    is a view of the aggregation, so what the reader sees and what the model
    (WS3) was given cannot drift apart.
    """
    p = stats.parametros
    lines = [
        "---",
        "type: progreso",
        f"fecha: {stats.generado.isoformat()}",
        f"desde: {stats.primera.isoformat() if stats.primera else ''}",
        f"hasta: {stats.ultima.isoformat() if stats.ultima else ''}",
        f"sesiones: {stats.sesiones_n}",
        "fuente: analiza",
        "---",
        "",
        "## Alcance",
        "",
        f"- Sesiones: {stats.sesiones_n} (examinadas: {stats.examinadas_n})",
        f"- Rango: {stats.primera.isoformat() if stats.primera else '—'} → "
        f"{stats.ultima.isoformat() if stats.ultima else '—'}",
        f"- Ejercicio: {stats.ejercicio or '(todos)'}",
        f"- Umbrales: ventana {p.ventana_n} · ausencia {p.ausencia_n} · "
        f"mínimo para narrativa {p.min_sesiones} · "
        f"hueco VAD {p.vad_gap_ratio:.0%}",
        "",
        "Las muletillas están subestimadas (Whisper las suprime): la cifra es "
        "una cota inferior, solo la tendencia es significativa.",
        "",
        "## Tendencias",
        "",
    ]

    if not stats.segmentos:
        lines += ["_Sin sesiones en el rango._", ""]
    for seg in stats.segmentos:
        lines += [
            f"### {seg.prompt_version or '(sin registrar)'} · whisper "
            f"{seg.whisper_model or '(sin registrar)'}",
            "",
            f"{plural(seg.sesiones_n, 'sesión', 'sesiones')} · "
            f"{seg.primera.isoformat()} → {seg.ultima.isoformat()}",
            "",
            *_tendencias_lines(seg.tendencias, p.ventana_n),
            "",
        ]

    if stats.fronteras:
        lines += [
            "## Fronteras de comparabilidad",
            "",
            "Cada una parte la serie en dos: los números de un lado y del otro "
            "nunca fueron comparables.",
            "",
            *[f"- {f}" for f in stats.fronteras],
            "",
        ]

    lines += ["## Patrones", ""]
    if stats.patrones:
        lines += [
            "| patrón | tipo | sesiones | instancias | primera | última | estado |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {_cell(r.etiqueta)} | {r.tipo_habitual} | {r.sesiones_n} | "
            f"{r.instancias_n} | {r.primera.isoformat()} | "
            f"{r.ultima.isoformat()} | {_estado_patron(r)} |"
            for r in stats.patrones
        ]
    else:
        lines.append("_Ningún patrón registrado en el rango._")
    lines.append("")
    if stats.otros_n:
        lines += [
            f"{plural(stats.otros_n, 'hallazgo', 'hallazgos')} sin id del "
            "vocabulario (`otro`): reales, pero fuera del seguimiento.",
            "",
        ]

    if stats.baja_confianza:
        lines += [
            "## Sesiones de baja confianza",
            "",
            "Habla detectada por el VAD que apenas llegó a transcribirse: toda "
            "métrica derivada de las palabras queda subestimada.",
            "",
            *[f"- {s}" for s in stats.baja_confianza],
            "",
        ]

    if stats.advertencias:
        lines += ["## Notas de lectura", ""]
        lines += [f"- {a}" for a in stats.advertencias]
        lines.append("")

    lines += ["## Lectura", ""]
    if narrativa is not None:
        lines += [narrativa, ""]
    elif not stats.narrativa:
        lines += [
            f"_Sin lectura: {plural(stats.sesiones_n, 'sesión', 'sesiones')}, "
            f"por debajo del mínimo de {p.min_sesiones}. Los números de arriba "
            "son completos; lo que "
            "se omite es la historia, que a esta escala sería una historia "
            "inventada._",
            "",
        ]
    else:
        lines += ["_Pendiente: el pase LLM se omitió (--no-llm)._", ""]
    return "\n".join(lines)


def output_base(root: Path, *, vault_layout: bool) -> Path:
    """The directory the three artifacts hang off.

    The single place that knows about vault layout: `{root}/Español` for a
    vault, `{root}` for a plain output dir.
    """
    return root / VAULT_SUBDIR if vault_layout else root


def _free_path(directory: Path, stem: str) -> Path:
    """{directory}/{stem}.md, appending " (2)", " (3)", … on collision."""
    path = directory / f"{stem}.md"
    n = 2
    while path.exists():
        path = directory / f"{stem} ({n}).md"
        n += 1
    return path


def note_path(base: Path, fecha: dt.date, ejercicio: str) -> Path:
    """{base}/Sesiones/YYYY-MM-DD {ejercicio}.md."""
    return _free_path(base / "Sesiones", f"{fecha.isoformat()} {ejercicio}")


def progreso_note_path(base: Path, fecha: dt.date) -> Path:
    """{base}/Progreso/YYYY-MM-DD progreso.md. Its own directory rather than
    Sesiones/: a progress report is about the corpus, not a member of it."""
    return _free_path(base / "Progreso", f"{fecha.isoformat()} progreso")


def progreso_raw_dir(base: Path, fecha: dt.date) -> Path:
    """{base}/analiza-raw/progreso-YYYY-MM-DD/ — holds the aggregation and,
    once WS3 lands, the narrative response."""
    path = base / "analiza-raw" / f"progreso-{fecha.isoformat()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OutputWriteError(f"failed creating {path}: {e}") from e
    return path


def write_note(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    except OSError as e:
        raise OutputWriteError(f"failed writing {path}: {e}") from e


def _widen_stats_header(csv_path: Path) -> None:
    """Bring a CSV written before a column was appended up to the contract.

    STATS_COLUMNS is append-only, so an older file's header is a *prefix* of
    the current one. DictWriter writes by fieldname and never consults the
    file, so appending a current row to an older file would produce data rows
    wider than their own header — DictReader would quietly shunt the extra
    values into its restkey and the new column would read as absent
    everywhere. Widening the header (old rows get empty cells, which is what
    they mean: not recorded) is the only non-destructive fix.

    A header that is not a prefix is not version skew — it is a different file,
    or one whose columns were reordered by hand. Refusing is correct: rewriting
    it would silently relabel every value in it.
    """
    with csv_path.open(newline="") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] == STATS_COLUMNS:
        return  # empty file: the header goes in on this append
    header = rows[0]
    if header != STATS_COLUMNS[: len(header)]:
        raise OutputWriteError(
            f"{csv_path} header {header} is not a prefix of the current "
            f"contract {STATS_COLUMNS}; refusing to rewrite it"
        )
    tmp = csv_path.with_name(f"{csv_path.name}.tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(STATS_COLUMNS)
        writer.writerows(
            [*r, *[""] * (len(STATS_COLUMNS) - len(r))] for r in rows[1:]
        )
    tmp.replace(csv_path)  # same directory, so the swap is atomic


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
        if not is_new:
            _widen_stats_header(csv_path)
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
