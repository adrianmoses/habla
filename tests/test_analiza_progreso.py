"""Progress aggregation tests (spec 034 WS2).

The property under test throughout is *refusal*: this feature exists because a
report built on the raw artifacts would narrate noise with confidence, so most
of what follows checks that the aggregation declines to conclude things —
across a provenance boundary, from a truncated session, below a window size,
under the minimum session count.
"""

import datetime as dt
from pathlib import Path
from unittest.mock import patch

from analiza import historial, note, patrones_b2, progreso
from analiza.config import ProgresoThresholds
from analiza.patrones_b2 import Patron
from analiza.progreso import Sesion

HOY = dt.date(2026, 9, 1)
PARAMS = ProgresoThresholds()


def sesion(dia: int, **kw: object) -> Sesion:
    """A session on 2026-08-{dia}, examined and finding nothing by default —
    an unexamined session (`patrones=None`) is the exception in a real corpus.
    """
    campos: dict[str, object] = {
        "ejercicio": "monologo",
        "patrones": {},
        "prompt_version": "examiner_v3",
        "whisper_model": "small",
        "vocab_version": patrones_b2.VOCAB_VERSION,
    }
    campos.update(kw)
    return Sesion(fecha=dt.date(2026, 8, dia), **campos)


def serie(valores: list[float], metrica: str = "wpm_gross") -> list[Sesion]:
    return [
        sesion(i + 1, metricas={metrica: v}) for i, v in enumerate(valores)
    ]


# ── Metric windows ──────────────────────────────────────────────────────────


def test_window_compares_first_n_against_last_n() -> None:
    t = progreso.metric_trend(
        "wpm_gross", "WPM", [50, 52, 54, 56, 58, 70, 72, 74, 76, 78], ventana_n=5
    )
    assert t.estado == "ok"
    assert t.primeras is not None and t.primeras.media == 54
    assert t.ultimas is not None and t.ultimas.media == 74
    assert t.delta == 20
    assert t.sesiones_n == 10


def test_window_declines_when_the_two_would_overlap() -> None:
    """Nine sessions with N=5 means one session sits on both sides, so the
    comparison would partly measure a number against itself."""
    t = progreso.metric_trend("wpm_gross", "WPM", [1] * 9, ventana_n=5)
    assert t.estado == "insuficiente"
    assert (t.primeras, t.ultimas, t.delta) == (None, None, None)
    assert t.faltan == 1
    assert t.sesiones_n == 9


def test_window_uses_only_the_sessions_carrying_the_metric() -> None:
    """A --no-llm session has no score. Its absence must not read as a zero,
    and the trend must say how many sessions are actually behind it."""
    sesiones = [
        *[
            sesion(i, metricas={"wpm_gross": 60.0, "score_total": 8.0})
            for i in range(1, 6)
        ],
        *[sesion(i, metricas={"wpm_gross": 60.0}) for i in range(6, 8)],
        *[
            sesion(i, metricas={"wpm_gross": 60.0, "score_total": 10.0})
            for i in range(8, 13)
        ],
    ]
    stats = progreso.aggregate(sesiones, hoy=HOY, parametros=PARAMS)
    por_metrica = {t.metrica: t for t in stats.segmentos[0].tendencias}
    assert por_metrica["score_total"].sesiones_n == 10
    assert por_metrica["score_total"].delta == 2
    assert por_metrica["wpm_gross"].sesiones_n == 12


def test_pauses_are_trended_per_minute_not_raw() -> None:
    """A raw pause count moves with session length; the derived rate does not,
    and only the rate is trended."""
    metricas = progreso.session_metrics(
        {"duration_s": "600", "pauses_n": "60", "wpm_gross": "80"}
    )
    assert metricas["pauses_per_min"] == 6.0
    assert "pauses_per_min" in dict(progreso.TREND_METRICS)
    assert "pauses_n" not in dict(progreso.TREND_METRICS)


def test_session_metrics_drops_blank_cells_rather_than_zeroing_them() -> None:
    metricas = progreso.session_metrics(
        {"wpm_gross": "80", "score_total": "", "mtld": "no", "calcos_n": "3"}
    )
    assert metricas == {"wpm_gross": 80.0, "calcos_n": 3.0}


# ── Segmentation ────────────────────────────────────────────────────────────


def test_a_prompt_version_boundary_produces_two_segments() -> None:
    sesiones = [
        *[sesion(i, prompt_version="examiner_v2") for i in range(1, 7)],
        *[sesion(i, prompt_version="examiner_v3") for i in range(7, 13)],
    ]
    stats = progreso.aggregate(sesiones, hoy=HOY, parametros=PARAMS)
    assert [s.prompt_version for s in stats.segmentos] == [
        "examiner_v2",
        "examiner_v3",
    ]
    assert [s.sesiones_n for s in stats.segmentos] == [6, 6]
    # Neither segment reaches 2×5, so no trend spans the boundary by accident.
    assert all(
        t.estado == "insuficiente" for s in stats.segmentos for t in s.tendencias
    )
    assert stats.fronteras == [
        "prompt_version: examiner_v2 → examiner_v3 en 2026-08-07 monologo"
    ]


def test_a_whisper_model_boundary_also_splits() -> None:
    sesiones = [
        *[sesion(i, whisper_model="small") for i in range(1, 4)],
        *[sesion(i, whisper_model="medium") for i in range(4, 7)],
    ]
    stats = progreso.aggregate(sesiones, hoy=HOY, parametros=PARAMS)
    assert [s.whisper_model for s in stats.segmentos] == ["small", "medium"]
    assert len(stats.fronteras) == 1
    assert "whisper_model" in stats.fronteras[0]


def test_one_provenance_pair_stays_one_segment() -> None:
    stats = progreso.aggregate(serie([60.0] * 12), hoy=HOY, parametros=PARAMS)
    assert len(stats.segmentos) == 1
    assert stats.fronteras == []


# ── Pattern recurrence ──────────────────────────────────────────────────────


def test_recurrence_counts_sessions_instances_and_span() -> None:
    sesiones = [
        sesion(1, patrones={"por-vs-para": 3}),
        sesion(2, patrones={"por-vs-para": 2, "concordancia-genero": 1}),
        sesion(3, patrones={"por-vs-para": 1}),
    ]
    por_id = {
        r.pattern_id: r
        for r in progreso.pattern_recurrence(sesiones, ausencia_n=3)
    }
    assert por_id["por-vs-para"].sesiones_n == 3
    assert por_id["por-vs-para"].instancias_n == 6
    assert por_id["por-vs-para"].primera == dt.date(2026, 8, 1)
    assert por_id["por-vs-para"].ultima == dt.date(2026, 8, 3)
    assert por_id["concordancia-genero"].sesiones_n == 1
    # Most recurrent first: the "focus next" ordering.
    ordenados = progreso.pattern_recurrence(sesiones, ausencia_n=3)
    assert [r.pattern_id for r in ordenados] == [
        "por-vs-para",
        "concordancia-genero",
    ]


def test_a_pattern_absent_for_n_conclusive_sessions_reads_as_gone() -> None:
    sesiones = [
        sesion(1, patrones={"por-vs-para": 2}),
        *[sesion(i, patrones={"concordancia-genero": 1}) for i in range(2, 5)],
    ]
    (recurrencia,) = [
        r
        for r in progreso.pattern_recurrence(sesiones, ausencia_n=3)
        if r.pattern_id == "por-vs-para"
    ]
    assert recurrencia.sesiones_desde_ultima == 3
    assert recurrencia.ausencias_concluyentes == 3
    assert recurrencia.estado == "ausente"


def test_a_pattern_in_the_last_session_is_not_gone() -> None:
    sesiones = [
        *[sesion(i, patrones={}) for i in range(1, 5)],
        sesion(5, patrones={"por-vs-para": 1}),
    ]
    (recurrencia,) = progreso.pattern_recurrence(sesiones, ausencia_n=3)
    assert recurrencia.sesiones_desde_ultima == 0
    assert recurrencia.estado == "persistente"


def test_absence_in_a_truncated_session_concludes_nothing() -> None:
    """Every measured run filled the examiner's 10-pattern cap, so a fault
    missing from a capped session may simply have ranked 11th."""
    sesiones = [
        sesion(1, patrones={"por-vs-para": 2}),
        *[
            sesion(i, patrones={"concordancia-genero": 1}, truncado=True)
            for i in range(2, 5)
        ],
    ]
    (recurrencia,) = [
        r
        for r in progreso.pattern_recurrence(sesiones, ausencia_n=3)
        if r.pattern_id == "por-vs-para"
    ]
    assert recurrencia.sesiones_desde_ultima == 3
    assert recurrencia.ausencias_concluyentes == 0
    assert recurrencia.estado == "no-concluyente"


def test_absence_in_a_backfilled_session_concludes_nothing() -> None:
    """Backfill saw the finding prose, not the transcript: a mis-key there
    manufactures a false absence as easily as a false presence."""
    sesiones = [
        sesion(1, patrones={"por-vs-para": 2}),
        *[sesion(i, patrones={}, backfilled=True) for i in range(2, 5)],
    ]
    (recurrencia,) = progreso.pattern_recurrence(sesiones, ausencia_n=3)
    assert recurrencia.estado == "no-concluyente"


def test_absence_in_a_session_with_unkeyed_rows_concludes_nothing() -> None:
    sesiones = [
        sesion(1, patrones={"por-vs-para": 2}),
        *[sesion(i, patrones={}, filas_sin_id=2) for i in range(2, 5)],
    ]
    (recurrencia,) = progreso.pattern_recurrence(sesiones, ausencia_n=3)
    assert recurrencia.estado == "no-concluyente"


def test_an_unexamined_session_neither_confirms_nor_denies() -> None:
    sesiones = [
        sesion(1, patrones={"por-vs-para": 2}),
        *[sesion(i, patrones=None, metricas={"wpm_gross": 60.0}) for i in range(2, 5)],
    ]
    (recurrencia,) = progreso.pattern_recurrence(sesiones, ausencia_n=3)
    # It is not counted as a session that went by, either: it never looked.
    assert recurrencia.sesiones_desde_ultima == 0
    assert recurrencia.estado == "persistente"

    stats = progreso.aggregate(sesiones, hoy=HOY, parametros=PARAMS)
    assert (stats.sesiones_n, stats.examinadas_n) == (4, 1)
    assert any("sin pase de examinador" in a for a in stats.advertencias)


def test_absence_before_an_id_existed_concludes_nothing() -> None:
    """The vocabulary grows. A pattern missing from an older session may be
    missing only because its id had not been written yet."""
    vocab = ("vocab_v1", "vocab_v2")
    nuevo = Patron("por-vs-para", "por vs para", "gramatica", (), desde="vocab_v2")
    viejo = Patron("concordancia-genero", "género", "gramatica", ())
    with (
        patch.object(patrones_b2, "VOCAB_VERSIONS", vocab),
        patch.object(patrones_b2, "PATRONES", [nuevo, viejo]),
    ):
        assert patrones_b2.ids_disponibles("vocab_v1") == frozenset(
            {"concordancia-genero"}
        )
        assert patrones_b2.ids_disponibles("vocab_v2") == frozenset(
            {"concordancia-genero", "por-vs-para"}
        )
        sesiones = [
            sesion(1, patrones={"por-vs-para": 2}, vocab_version="vocab_v2"),
            *[
                sesion(i, patrones={}, vocab_version="vocab_v1")
                for i in range(2, 5)
            ],
        ]
        (recurrencia,) = [
            r
            for r in progreso.pattern_recurrence(sesiones, ausencia_n=3)
            if r.pattern_id == "por-vs-para"
        ]
        assert recurrencia.ausencias_concluyentes == 0
        assert recurrencia.estado == "no-concluyente"


def test_an_unrecorded_vocab_version_reads_as_the_baseline() -> None:
    """Conservative on purpose: assuming fewer ids existed can only make the
    report more cautious about absence, never less."""
    assert patrones_b2.version_index("") == 0
    assert patrones_b2.version_index("vocab_v99") == 0
    assert patrones_b2.ids_disponibles("") == frozenset(patrones_b2.PATRON_IDS)


# ── Low-confidence flagging ─────────────────────────────────────────────────


def test_low_confidence_flag_on_both_sides_of_the_threshold() -> None:
    sesiones = [
        sesion(1, vad_gap_ratio=0.101),
        sesion(2, vad_gap_ratio=0.10),
        sesion(3, vad_gap_ratio=None),
    ]
    stats = progreso.aggregate(sesiones, hoy=HOY, parametros=PARAMS)
    assert stats.baja_confianza == ["2026-08-01 monologo"]


def test_low_confidence_threshold_is_configurable() -> None:
    sesiones = [sesion(1, vad_gap_ratio=0.05)]
    params = ProgresoThresholds(vad_gap_ratio=0.01)
    stats = progreso.aggregate(sesiones, hoy=HOY, parametros=params)
    assert stats.baja_confianza == ["2026-08-01 monologo"]


# ── Range selection, the narrative gate, determinism ────────────────────────


def test_select_filters_by_range_and_exercise_and_sorts() -> None:
    sesiones = [
        sesion(5, ejercicio="narrar-dia"),
        sesion(1),
        sesion(9),
    ]
    elegidas = progreso.select(
        sesiones, desde=dt.date(2026, 8, 2), hasta=dt.date(2026, 8, 9)
    )
    assert [s.fecha.day for s in elegidas] == [5, 9]
    solo = progreso.select(sesiones, ejercicio="monologo")
    assert [s.fecha.day for s in solo] == [1, 9]


def test_below_the_minimum_the_numbers_stand_and_the_story_does_not() -> None:
    stats = progreso.aggregate(serie([60.0] * 7), hoy=HOY, parametros=PARAMS)
    assert stats.sesiones_n == 7
    assert stats.narrativa is False
    # The aggregation itself is complete: only the narrative is declined.
    assert stats.segmentos and stats.parametros.min_sesiones == 8

    nota = note.render_progreso_note(stats)
    assert "por debajo del mínimo de 8" in nota


def test_at_the_minimum_a_narrative_is_allowed() -> None:
    stats = progreso.aggregate(serie([60.0] * 8), hoy=HOY, parametros=PARAMS)
    assert stats.narrativa is True


def test_the_minimum_is_configurable() -> None:
    params = ProgresoThresholds(min_sesiones=3)
    stats = progreso.aggregate(serie([60.0] * 3), hoy=HOY, parametros=params)
    assert stats.narrativa is True


def test_aggregating_twice_is_byte_identical() -> None:
    sesiones = [
        sesion(1, patrones={"por-vs-para": 2}, metricas={"wpm_gross": 55.0}),
        sesion(2, patrones={"concordancia-genero": 1}, metricas={"wpm_gross": 61.0}),
        sesion(2, ejercicio="narrar-dia", patrones={"por-vs-para": 1}),
        sesion(3, patrones={}, truncado=True, vad_gap_ratio=0.4),
    ]
    primera = progreso.aggregate(sesiones, hoy=HOY, parametros=PARAMS)
    segunda = progreso.aggregate(
        list(reversed(sesiones)), hoy=HOY, parametros=PARAMS
    )
    assert primera.model_dump_json() == segunda.model_dump_json()


# ── historial: joining the corpus off disk ──────────────────────────────────


CSV_ROW = {
    "date": "2026-08-01", "ejercicio": "monologo", "tema": "viajes",
    "duration_s": "600", "wpm_gross": "60", "wpm_articulation": "80",
    "pauses_n": "30", "pause_max_s": "4", "fillers_per_min": "2",
    "connectors_unique": "3", "formal_ratio": "0.3", "mtld": "40",
    "errors_n": "2", "calcos_n": "1", "score_total": "8",
    "whisper_model": "small", "prompt_version": "examiner_v3",
    "vocab_version": "vocab_v1",
}

EXAMINER_JSON = {
    "errores": [
        {"pattern_id": "por-vs-para", "instancias": ["a", "b"]},
        {"pattern_id": "otro", "instancias": ["c"]},
        {"instancias": ["d"]},
    ]
}


def _corpus(
    base: Path, rows: list[dict[str, str]], columns: list[str] | None = None
) -> None:
    import csv

    base.mkdir(parents=True, exist_ok=True)
    with (base / "analiza-stats.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns or note.STATS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _raw(base: Path, nombre: str, **archivos: object) -> Path:
    import json

    d = base / "analiza-raw" / nombre
    d.mkdir(parents=True, exist_ok=True)
    for stem, payload in archivos.items():
        (d / f"{stem}.json").write_text(
            payload if isinstance(payload, str) else json.dumps(payload)
        )
    return d


def test_load_joins_the_csv_row_with_its_stored_artifacts(tmp_path: Path) -> None:
    _corpus(tmp_path, [CSV_ROW])
    _raw(
        tmp_path,
        "2026-08-01-monologo",
        examiner=EXAMINER_JSON,
        metrics={"duration_s": 600.0, "vad_transcript_gap_s": 60.0},
    )
    (sesion_leida,), advertencias = historial.load_sesiones(tmp_path)

    assert sesion_leida.patrones == {"por-vs-para": 2}
    assert sesion_leida.otros_n == 1  # the `otro` row: real, but untrackable
    assert sesion_leida.filas_sin_id == 1  # never reached by the backfill
    assert sesion_leida.truncado is False
    assert sesion_leida.backfilled is False
    assert sesion_leida.vad_gap_ratio == 0.1
    assert sesion_leida.metricas["wpm_gross"] == 60.0
    assert sesion_leida.metricas["pauses_per_min"] == 3.0
    assert sesion_leida.vocab_version == "vocab_v1"
    assert advertencias == []


def test_load_marks_a_backfilled_session(tmp_path: Path) -> None:
    _corpus(tmp_path, [CSV_ROW])
    _raw(
        tmp_path,
        "2026-08-01-monologo",
        examiner={"errores": [{"pattern_id": "por-vs-para", "instancias": ["a"]}]},
        backfill={"backfill_version": "backfill_v1"},
    )
    (leida,), _ = historial.load_sesiones(tmp_path)
    assert leida.backfilled is True


def test_load_marks_a_session_at_the_pattern_cap(tmp_path: Path) -> None:
    from analiza.examiner import MAX_PATRONES

    _corpus(tmp_path, [CSV_ROW])
    _raw(
        tmp_path,
        "2026-08-01-monologo",
        examiner={
            "errores": [
                {"pattern_id": "por-vs-para", "instancias": ["a"]}
                for _ in range(MAX_PATRONES)
            ]
        },
    )
    (leida,), _ = historial.load_sesiones(tmp_path)
    assert leida.truncado is True


def test_a_session_without_artifacts_is_unexamined_not_empty(tmp_path: Path) -> None:
    _corpus(tmp_path, [CSV_ROW])
    (leida,), _ = historial.load_sesiones(tmp_path)
    assert leida.patrones is None
    assert leida.examinada is False


def test_a_corrupt_examiner_file_costs_only_its_patterns(tmp_path: Path) -> None:
    _corpus(tmp_path, [CSV_ROW])
    _raw(tmp_path, "2026-08-01-monologo", examiner="{not json")
    (leida,), _ = historial.load_sesiones(tmp_path)
    assert leida.patrones is None
    assert leida.metricas["wpm_gross"] == 60.0  # the CSV row still counts


def test_two_sessions_sharing_a_raw_dir_contribute_no_patterns(tmp_path: Path) -> None:
    """note.raw_dir reuses the directory, so the artifacts belong to whichever
    ran last. Counting them for both rows would invent recurrence."""
    _corpus(tmp_path, [CSV_ROW, {**CSV_ROW, "wpm_gross": "70"}])
    _raw(tmp_path, "2026-08-01-monologo", examiner=EXAMINER_JSON)
    sesiones, advertencias = historial.load_sesiones(tmp_path)
    assert [s.patrones for s in sesiones] == [None, None]
    assert any("comparten" in a for a in advertencias)


def test_a_pre_column_csv_is_read_and_flagged(tmp_path: Path) -> None:
    older = note.STATS_COLUMNS[:-1]
    _corpus(tmp_path, [{k: v for k, v in CSV_ROW.items() if k in older}], older)
    (leida,), advertencias = historial.load_sesiones(tmp_path)
    assert leida.vocab_version == ""
    assert any("vocab_version" in a for a in advertencias)


def test_a_row_without_a_date_is_skipped_not_fatal(tmp_path: Path) -> None:
    _corpus(tmp_path, [{**CSV_ROW, "date": ""}, CSV_ROW])
    sesiones, advertencias = historial.load_sesiones(tmp_path)
    assert len(sesiones) == 1
    assert any("sin fecha" in a for a in advertencias)


def test_a_missing_csv_is_an_error_not_an_empty_report(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(historial.HistorialError):
        historial.load_sesiones(tmp_path)


# ── The note ────────────────────────────────────────────────────────────────


def test_the_note_reports_absence_as_an_observation_not_a_verdict() -> None:
    sesiones = [
        sesion(1, patrones={"por-vs-para": 2}),
        *[sesion(i, patrones={}) for i in range(2, 12)],
    ]
    stats = progreso.aggregate(sesiones, hoy=HOY, parametros=PARAMS)
    nota = note.render_progreso_note(stats)
    assert "sin aparecer en 10 sesiones" in nota
    assert "resuelto" not in nota.lower()


def test_the_note_names_every_comparability_boundary() -> None:
    sesiones = [
        sesion(1, prompt_version="examiner_v2"),
        sesion(2, prompt_version="examiner_v3"),
        sesion(3, prompt_version="examiner_v3", whisper_model="medium"),
    ]
    stats = progreso.aggregate(sesiones, hoy=HOY, parametros=PARAMS)
    nota = note.render_progreso_note(stats)
    assert "examiner_v2 → examiner_v3" in nota
    assert "small → medium" in nota
    assert len(stats.segmentos) == 3


def test_the_note_carries_the_narrative_when_there_is_one() -> None:
    stats = progreso.aggregate(serie([60.0] * 8), hoy=HOY, parametros=PARAMS)
    nota = note.render_progreso_note(stats, "Vas mejor en fluidez.")
    assert "Vas mejor en fluidez." in nota
    assert "por debajo del mínimo" not in nota
