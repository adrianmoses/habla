"""Note/CSV output tests (spec §2F)."""

import datetime as dt
from pathlib import Path

import pytest

from analiza import note
from analiza.examiner import (
    ErrorRow,
    ExaminerResult,
    Mejora,
    Puntuacion,
    SubjuntivoCheck,
)

FECHA = dt.date(2026, 7, 19)

METRICS: dict[str, float | int] = {
    "duration_s": 120.0, "speech_time_s": 100.0, "wpm_gross": 90.0,
    "wpm_articulation": 108.0, "pauses_n": 5, "pauses_total_s": 12.0,
    "pause_max_s": 3.2, "pauses_midclause_n": 2, "fillers_n": 4,
    "fillers_per_min": 2.0, "connectors_unique_n": 3,
    "connectors_formal_ratio": 0.33, "ttr": 0.6, "mtld": 42.0,
    "repeats_n": 1, "low_conf_spans_n": 0, "vad_transcript_gap_s": 1.1,
}


def examiner_result() -> ExaminerResult:
    return ExaminerResult(
        puntuaciones=[
            Puntuacion(criterio=c, puntuacion=2, justificacion="ok")
            for c in ("coherencia", "fluidez", "correccion", "alcance")
        ],
        errores=[
            ErrorRow(dije="fui en casa", deberia_ser="fui a casa", por_que="régimen")
        ],
        subjuntivo=[
            SubjuntivoCheck(conector="a menos que", frase="a menos que vengas",
                            correcto=True)
        ],
        mejoras=[
            Mejora(
                rodeo="la cosa para abrir", chunk_b2="el abrelatas", contexto="cocina"
            ),
            Mejora(rodeo="muy muy grande", chunk_b2="enorme", contexto="descripción"),
        ],
        enfoque_proxima_sesion="subjuntivo tras conectores concesivos",
    )


def test_render_note_with_examiner() -> None:
    md = note.render_note(
        fecha=FECHA, ejercicio="monologo", tema="viajes", duration_s=120.0,
        metrics=METRICS, examiner=examiner_result(), prompt_version="examiner_v1",
    )
    assert md.startswith("---\ntype: sesion\n")
    assert "fecha: 2026-07-19" in md
    assert "duracion: 2.0" in md
    assert "tema: viajes" in md
    assert "cota inferior" in md  # fillers labeled as floor
    assert "| fui en casa | fui a casa | régimen |" in md
    assert "**Total: 8/12**" in md
    assert "## Chunks capturados" in md
    assert "- el abrelatas :: cocina" in md
    assert "examiner_v1" in md


def test_render_note_without_examiner_marks_pending() -> None:
    md = note.render_note(
        fecha=FECHA, ejercicio="monologo", tema=None, duration_s=60.0,
        metrics=METRICS, examiner=None, prompt_version="examiner_v1",
    )
    assert "Pendiente" in md
    assert "## Chunks capturados" not in md


def test_note_path_collision(tmp_path: Path) -> None:
    first = note.note_path(tmp_path, FECHA, "monologo")
    assert first == tmp_path / "Español" / "Sesiones" / "2026-07-19 monologo.md"
    note.write_note(first, "x")
    second = note.note_path(tmp_path, FECHA, "monologo")
    assert second.name == "2026-07-19 monologo (2).md"
    note.write_note(second, "x")
    assert note.note_path(tmp_path, FECHA, "monologo").name == (
        "2026-07-19 monologo (3).md"
    )


def _row() -> dict[str, object]:
    return {
        "date": "2026-07-19", "ejercicio": "monologo", "tema": "viajes",
        "duration_s": 120.0, "wpm_gross": 90.0, "wpm_articulation": 108.0,
        "pauses_n": 5, "pause_max_s": 3.2, "fillers_per_min": 2.0,
        "connectors_unique": 3, "formal_ratio": 0.33, "mtld": 42.0,
        "errors_n": 1, "score_total": 8, "prompt_version": "examiner_v1",
    }


def test_append_stats_row_writes_header_once(tmp_path: Path) -> None:
    note.append_stats_row(tmp_path, _row())
    note.append_stats_row(tmp_path, _row())
    lines = (tmp_path / "Español" / "analiza-stats.csv").read_text().splitlines()
    assert lines[0] == ",".join(note.STATS_COLUMNS)
    assert len(lines) == 3


def test_append_stats_row_rejects_wrong_keys(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        note.append_stats_row(tmp_path, {"date": "2026-07-19"})


def test_raw_dir_created(tmp_path: Path) -> None:
    raw = note.raw_dir(tmp_path, FECHA, "monologo")
    assert raw == tmp_path / "Español" / "analiza-raw" / "2026-07-19-monologo"
    assert raw.is_dir()
