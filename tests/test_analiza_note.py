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
            ErrorRow(
                pattern_id="calco-hacer-sentido",
                tipo="calco",
                patron="hacer sentido",
                deberia_ser="tener sentido",
                por_que="traducción literal de «make sense»",
                instancias=["eso no hace sentido", "no hace sentido para mí"],
            ),
            ErrorRow(
                pattern_id="preposicion-lugar",
                tipo="gramatica",
                patron="régimen preposicional con verbos de movimiento",
                deberia_ser="fui a casa",
                por_que="régimen",
                instancias=["fui en casa"],
            ),
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
        metrics=METRICS, examiner=examiner_result(), prompt_version="examiner_v2",
    )
    assert md.startswith("---\ntype: sesion\n")
    assert "fecha: 2026-07-19" in md
    assert "duracion: 2.0" in md
    assert "tema: viajes" in md
    assert "cota inferior" in md  # fillers labeled as floor
    assert "**Total: 8/12**" in md
    assert "## Chunks capturados" in md
    assert "- el abrelatas :: cocina" in md
    assert "examiner_v2" in md


def test_render_note_separates_calcos_from_other_errors() -> None:
    md = note.render_note(
        fecha=FECHA, ejercicio="monologo", tema="viajes", duration_s=120.0,
        metrics=METRICS, examiner=examiner_result(), prompt_version="examiner_v2",
    )
    calcos, errores = md.split("## Errores")
    # Calque section: own heading, instance count, every instance quoted.
    assert "## Calcos" in calcos
    assert "**hacer sentido** → tener sentido" in calcos
    assert "(2×)" in calcos
    assert "“eso no hace sentido”" in calcos
    assert "“no hace sentido para mí”" in calcos
    # ...and it does not reappear in the errors table below.
    assert "hacer sentido" not in errores
    assert "| régimen preposicional con verbos de movimiento | fui a casa |" in errores
    assert "| gramatica | fui en casa |" in errores


def test_render_note_escapes_pipes_in_error_table() -> None:
    """A pipe in LLM-supplied text must not split the markdown row."""
    result = examiner_result()
    result.errores = [
        ErrorRow(
            pattern_id="palabra-imprecisa",
            tipo="lexico", patron="a | b", deberia_ser="c", por_que="d\ne",
            instancias=["f | g"],
        )
    ]
    md = note.render_note(
        fecha=FECHA, ejercicio="monologo", tema=None, duration_s=120.0,
        metrics=METRICS, examiner=result, prompt_version="examiner_v2",
    )
    row = next(
        line for line in md.splitlines() if line.startswith("| a ")
    )
    assert row == r"| a \| b | c | d e | lexico | f \| g |"
    assert row.count("|") - row.count(r"\|") == 6  # 5 cells → 6 delimiters


def test_render_note_no_calcos_marks_section_empty() -> None:
    result = examiner_result()
    result.errores = [e for e in result.errores if e.tipo != "calco"]
    md = note.render_note(
        fecha=FECHA, ejercicio="monologo", tema=None, duration_s=120.0,
        metrics=METRICS, examiner=result, prompt_version="examiner_v2",
    )
    calcos = md.split("## Errores")[0]
    assert "## Calcos" in calcos
    assert "_Ninguno visible en la transcripción._" in calcos


def test_render_note_without_examiner_marks_pending() -> None:
    md = note.render_note(
        fecha=FECHA, ejercicio="monologo", tema=None, duration_s=60.0,
        metrics=METRICS, examiner=None, prompt_version="examiner_v2",
    )
    assert "Pendiente" in md
    assert "## Chunks capturados" not in md
    assert "## Calcos" not in md


def test_output_base_vault_layout_nests_under_espanol(tmp_path: Path) -> None:
    assert note.output_base(tmp_path, vault_layout=True) == tmp_path / "Español"


def test_output_base_plain_layout_is_flat(tmp_path: Path) -> None:
    """No vault → the three artifacts hang directly off the output dir."""
    base = note.output_base(tmp_path, vault_layout=False)
    assert base == tmp_path
    nota, raw = note.reserve_session(base, FECHA, "monologo")
    assert nota == tmp_path / "Sesiones" / "2026-07-19 monologo.md"
    assert raw == tmp_path / "analiza-raw" / "2026-07-19-monologo"
    note.append_stats_row(base, _row())
    assert (tmp_path / "analiza-stats.csv").exists()
    assert "Español" not in str(base)


def test_a_second_session_that_day_gets_its_own_note_and_artifacts(
    tmp_path: Path,
) -> None:
    """Three monólogos in one afternoon is ordinary practice. The raw
    directory used to be keyed on (date, exercise) alone and reused, so each
    run silently overwrote the previous one's examiner.json — and progreso,
    unable to tell which CSV row the survivors belonged to, then dropped the
    patterns for the whole day."""
    base = note.output_base(tmp_path, vault_layout=True)
    espanol = tmp_path / "Español"

    primera_nota, primer_raw = note.reserve_session(base, FECHA, "monologo")
    assert primera_nota == espanol / "Sesiones" / "2026-07-19 monologo.md"
    assert primer_raw == espanol / "analiza-raw" / "2026-07-19-monologo"
    note.write_note(primera_nota, "x")
    note.make_raw_dir(primer_raw)

    segunda_nota, segundo_raw = note.reserve_session(base, FECHA, "monologo")
    assert segunda_nota.name == "2026-07-19 monologo (2).md"
    assert segundo_raw.name == "2026-07-19-monologo (2)"
    note.write_note(segunda_nota, "x")
    note.make_raw_dir(segundo_raw)

    tercera_nota, tercer_raw = note.reserve_session(base, FECHA, "monologo")
    assert tercera_nota.name == "2026-07-19 monologo (3).md"
    assert tercer_raw.name == "2026-07-19-monologo (3)"


def test_the_note_and_its_artifacts_share_an_ordinal(tmp_path: Path) -> None:
    """Allocated together on purpose: a note whose ordinal disagrees with its
    directory is a session pointing at someone else's evidence."""
    base = note.output_base(tmp_path, vault_layout=True)
    # Only the raw directory exists — a run that died before writing its note.
    note.make_raw_dir(base / "analiza-raw" / "2026-07-19-monologo")

    nota, raw = note.reserve_session(base, FECHA, "monologo")
    assert nota.name == "2026-07-19 monologo (2).md"
    assert raw.name == "2026-07-19-monologo (2)"


def _row() -> dict[str, object]:
    return {
        "date": "2026-07-19", "ejercicio": "monologo", "tema": "viajes",
        "duration_s": 120.0, "wpm_gross": 90.0, "wpm_articulation": 108.0,
        "pauses_n": 5, "pause_max_s": 3.2, "fillers_per_min": 2.0,
        "connectors_unique": 3, "formal_ratio": 0.33, "mtld": 42.0,
        "errors_n": 2, "calcos_n": 1, "score_total": 8,
        "whisper_model": "small", "prompt_version": "examiner_v2",
        "vocab_version": "vocab_v1",
    }


def test_append_stats_row_writes_header_once(tmp_path: Path) -> None:
    base = note.output_base(tmp_path, vault_layout=True)
    note.append_stats_row(base, _row())
    note.append_stats_row(base, _row())
    lines = (tmp_path / "Español" / "analiza-stats.csv").read_text().splitlines()
    assert lines[0] == ",".join(note.STATS_COLUMNS)
    assert len(lines) == 3


def test_append_stats_row_rejects_wrong_keys(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        note.append_stats_row(tmp_path, {"date": "2026-07-19"})


def test_raw_dir_created(tmp_path: Path) -> None:
    base = note.output_base(tmp_path, vault_layout=True)
    _, reserved = note.reserve_session(base, FECHA, "monologo")
    raw = note.make_raw_dir(reserved)
    assert raw == tmp_path / "Español" / "analiza-raw" / "2026-07-19-monologo"
    assert raw.is_dir()


def _legacy_csv(base: Path, columns: list[str]) -> Path:
    """A stats CSV as an older build wrote it, before a column was appended."""
    base.mkdir(parents=True, exist_ok=True)
    path = base / "analiza-stats.csv"
    row = _row()
    path.write_text(
        ",".join(columns)
        + "\n"
        + ",".join(str(row[c]) for c in columns)
        + "\n"
    )
    return path


def test_append_stats_row_widens_a_narrower_header(tmp_path: Path) -> None:
    """A row wider than the file's header would misalign every reader, so the
    header is brought up to the contract and old rows padded."""
    older = note.STATS_COLUMNS[:-1]
    path = _legacy_csv(tmp_path, older)

    note.append_stats_row(tmp_path, _row())

    lines = path.read_text().splitlines()
    assert lines[0] == ",".join(note.STATS_COLUMNS)
    # The pre-existing row keeps its values and gains an empty cell — "not
    # recorded", which is exactly what it is.
    assert lines[1].endswith(",")
    assert len(lines[1].split(",")) == len(note.STATS_COLUMNS)
    # The appended row carries the new column's value in the new column.
    assert lines[2].split(",")[-1] == str(_row()["vocab_version"])
    assert len(lines) == 3


def test_append_stats_row_refuses_a_reordered_header(tmp_path: Path) -> None:
    """Not version skew: rewriting it would relabel every value in the file."""
    scrambled = list(reversed(note.STATS_COLUMNS))
    _legacy_csv(tmp_path, scrambled)
    with pytest.raises(note.OutputWriteError):
        note.append_stats_row(tmp_path, _row())
