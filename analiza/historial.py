"""Reading the stored corpus back (spec 034 WS2) — the I/O side of progreso.

`note.py` writes the three artifacts; this reads them. It is the only place
that touches the filesystem on the progress path, which is what lets
`progreso.py` claim to be pure and lets its tests run without a corpus.

Nothing here interprets: every judgment about what a session can be trusted to
say lives in `progreso.py`. This module's whole job is to join the CSV row
with the artifacts beside it and report, in plain warnings, whatever it could
not join.
"""

import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

from analiza.examiner import MAX_PATRONES
from analiza.note import STATS_COLUMNS
from analiza.patrones_b2 import PATRON_IDS, PatternId
from analiza.progreso import Sesion, session_metrics

STATS_FILENAME = "analiza-stats.csv"

_TRACKED: frozenset[str] = frozenset(PATRON_IDS)


class HistorialError(Exception):
    """The stats CSV is missing or unreadable — there is no corpus to report on."""


def stats_path(base: Path) -> Path:
    return base / STATS_FILENAME


def read_stats_rows(base: Path) -> list[dict[str, str]]:
    """Every row of the stats CSV, as written.

    Read by header rather than by position: the CSV is append-only but has
    gained columns, so older files are narrower than STATS_COLUMNS and a
    positional read would shift every value in them.
    """
    path = stats_path(base)
    try:
        with path.open(newline="") as f:
            return [
                {k: (v or "") for k, v in row.items() if k is not None}
                for row in csv.DictReader(f)
            ]
    except FileNotFoundError as e:
        raise HistorialError(f"no stats CSV at {path}") from e
    except OSError as e:
        raise HistorialError(f"failed reading {path}: {e}") from e


def _read_json(path: Path) -> Any | None:
    """Parsed JSON, or None when the file is absent or unreadable. A corrupt
    sidecar degrades that one session; it must not strand the report."""
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _patrones_de_examiner(
    payload: Any,
) -> tuple[dict[PatternId, int], int, int, bool] | None:
    """(patterns → instances, otros_n, filas_sin_id, truncado) from a stored
    examiner payload, or None when it is not one.

    Instance counts come from `len(instancias)`, which is the severity signal
    the v2 pattern grouping introduced; a row that somehow carries none still
    counts as one occurrence, because it was reported as a finding.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("errores"), list):
        return None
    patrones: dict[PatternId, int] = {}
    otros_n = 0
    sin_id = 0
    errores: list[Any] = payload["errores"]
    for row in errores:
        if not isinstance(row, dict):
            sin_id += 1
            continue
        pattern_id = row.get("pattern_id")
        instancias = max(1, len(row.get("instancias") or []))
        if pattern_id is None:
            sin_id += 1
        elif pattern_id in _TRACKED:
            key: PatternId = pattern_id
            patrones[key] = patrones.get(key, 0) + instancias
        else:
            # `otro`, or an id retired from the vocabulary since. Either way
            # there is no key to track it by.
            otros_n += 1
    return patrones, otros_n, sin_id, len(errores) >= MAX_PATRONES


def _vad_gap_ratio(payload: Any) -> float | None:
    """Untranscribed VAD speech as a share of the recording."""
    if not isinstance(payload, dict):
        return None
    gap = payload.get("vad_transcript_gap_s")
    duration = payload.get("duration_s")
    if not isinstance(gap, int | float) or not isinstance(duration, int | float):
        return None
    if duration <= 0:
        return None
    return round(gap / duration, 4)


def _sesion(row: dict[str, str], raw: Path | None) -> Sesion:
    """One CSV row joined with the artifacts in its raw directory."""
    fecha = dt.date.fromisoformat(row["date"])
    patrones: dict[PatternId, int] | None = None
    otros_n = sin_id = 0
    truncado = backfilled = False
    gap_ratio: float | None = None

    if raw is not None:
        examinado = _patrones_de_examiner(_read_json(raw / "examiner.json"))
        if examinado is not None:
            patrones, otros_n, sin_id, truncado = examinado
        backfilled = (raw / "backfill.json").exists()
        gap_ratio = _vad_gap_ratio(_read_json(raw / "metrics.json"))

    return Sesion(
        fecha=fecha,
        ejercicio=row.get("ejercicio", ""),
        tema=row.get("tema", ""),
        metricas=session_metrics(row),
        whisper_model=row.get("whisper_model", ""),
        prompt_version=row.get("prompt_version", ""),
        vocab_version=row.get("vocab_version", ""),
        patrones=patrones,
        otros_n=otros_n,
        filas_sin_id=sin_id,
        truncado=truncado,
        backfilled=backfilled,
        vad_gap_ratio=gap_ratio,
    )


def load_sesiones(base: Path) -> tuple[list[Sesion], list[str]]:
    """Every recorded session under `base`, plus what could not be read.

    Warnings are returned rather than raised: a report over 30 sessions must
    not fail because one row has a hand-edited date, and it must not silently
    drop that row either.

    The raw directory is keyed `{fecha}-{ejercicio}`, so two sessions of the
    same exercise on one day resolve to one directory — and `note.raw_dir`
    reuses it, meaning the artifacts on disk belong to whichever ran last.
    Those rows are joined to no artifacts at all rather than to someone
    else's: counting one session's patterns twice would invent recurrence,
    which is the one thing this feature must never do.
    """
    rows = read_stats_rows(base)
    sesiones: list[Sesion] = []
    advertencias: list[str] = []

    faltan = [c for c in STATS_COLUMNS if rows and c not in rows[0]]
    if faltan:
        advertencias.append(
            f"el CSV precede a estas columnas: {', '.join(faltan)}; esas "
            "sesiones se leen con el valor por defecto"
        )

    dirs: dict[str, int] = {}
    for row in rows:
        nombre = f"{row.get('date', '')}-{row.get('ejercicio', '')}"
        dirs[nombre] = dirs.get(nombre, 0) + 1

    for i, row in enumerate(rows, start=1):
        if not row.get("date"):
            advertencias.append(f"fila {i} del CSV sin fecha: ignorada")
            continue
        nombre = f"{row['date']}-{row.get('ejercicio', '')}"
        raw = base / "analiza-raw" / nombre
        compartida = dirs[nombre] > 1
        if compartida:
            advertencias.append(
                f"{dirs[nombre]} sesiones comparten {nombre}/: se cuentan sus "
                "métricas, no sus patrones"
            )
        try:
            sesiones.append(
                _sesion(row, None if compartida or not raw.is_dir() else raw)
            )
        except ValueError as e:
            advertencias.append(f"fila {i} del CSV ilegible ({e}): ignorada")

    # De-duplicate: one collision produces one warning per row involved.
    vistas: list[str] = []
    for a in advertencias:
        if a not in vistas:
            vistas.append(a)
    return sesiones, vistas
