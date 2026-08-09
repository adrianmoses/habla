"""Backfill tests (spec 034 WS1): retroactive pattern_id assignment.

The corpus these run against is the one thing progress tracking is built on,
so the properties that matter are: never lose data, never half-write a file,
and never let one bad session strand the rest.
"""

import datetime as dt
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from analiza import backfill
from analiza.config import Config

TODAY = dt.date(2026, 8, 10)

V2_PAYLOAD: dict[str, Any] = {
    "puntuaciones": [
        {"criterio": c, "puntuacion": 2, "justificacion": "ok"}
        for c in ("coherencia", "fluidez", "correccion", "alcance")
    ],
    "errores": [
        {
            "tipo": "calco",
            "patron": "hacer sentido",
            "deberia_ser": "tener sentido",
            "por_que": "traducción literal",
            "instancias": ["eso no hace sentido"],
        },
        {
            "tipo": "gramatica",
            "patron": "por vs para",
            "deberia_ser": "para",
            "por_que": "finalidad",
            "instancias": ["lo hice por comprar pan"],
        },
    ],
    "subjuntivo": [],
    "mejoras": [
        {"rodeo": "a", "chunk_b2": "b", "contexto": "c"},
        {"rodeo": "d", "chunk_b2": "e", "contexto": "f"},
    ],
    "enfoque_proxima_sesion": "foco",
}


def _session(root: Path, name: str, payload: Any) -> Path:
    d = root / "analiza-raw" / name
    d.mkdir(parents=True)
    p = d / "examiner.json"
    p.write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    )
    return p


def _assignment(*pairs: tuple[int, str]) -> MagicMock:
    response = MagicMock()
    response.parsed_output = backfill.AsignacionResult(
        asignaciones=[{"indice": i, "pattern_id": p} for i, p in pairs]  # type: ignore[list-item]
    )
    response.stop_reason = "end_turn"
    return response


def _config() -> Config:
    return Config()


# ── discovery and idempotency ──────────────────────────────────────────────


def test_needs_backfill_detects_missing_ids() -> None:
    assert backfill.needs_backfill(V2_PAYLOAD)
    done = {**V2_PAYLOAD, "errores": [
        {**r, "pattern_id": "otro"} for r in V2_PAYLOAD["errores"]
    ]}
    assert not backfill.needs_backfill(done)


def test_a_session_with_no_errors_needs_nothing() -> None:
    """No error rows means no key to assign — not an empty backfill to redo
    on every run."""
    assert not backfill.needs_backfill({**V2_PAYLOAD, "errores": []})


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_already_assigned_file_is_skipped_without_calling_the_model(
    mock_cls: MagicMock, tmp_path: Path
) -> None:
    done = {**V2_PAYLOAD, "errores": [
        {**r, "pattern_id": "por-vs-para"} for r in V2_PAYLOAD["errores"]
    ]}
    p = _session(tmp_path, "2026-08-01-monologo", done)
    before = p.read_text()

    out = backfill.backfill_file(p, _config(), dry_run=False, today=TODAY)

    assert out.status == "skipped"
    assert p.read_text() == before
    assert mock_cls.return_value.messages.parse.call_count == 0


# ── assignment ─────────────────────────────────────────────────────────────


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_assigns_in_place_and_preserves_the_rest_of_the_payload(
    mock_cls: MagicMock, tmp_path: Path
) -> None:
    mock_cls.return_value.messages.parse.return_value = _assignment(
        (0, "calco-hacer-sentido"), (1, "por-vs-para")
    )
    p = _session(tmp_path, "2026-08-01-monologo", V2_PAYLOAD)

    out = backfill.backfill_file(p, _config(), dry_run=False, today=TODAY)

    assert out.status == "assigned" and out.assigned == 2
    written = json.loads(p.read_text())
    assert [r["pattern_id"] for r in written["errores"]] == [
        "calco-hacer-sentido",
        "por-vs-para",
    ]
    # Everything else survives byte-for-byte in meaning — this rewrites a file
    # that is the only record of the session.
    assert written["puntuaciones"] == V2_PAYLOAD["puntuaciones"]
    assert written["mejoras"] == V2_PAYLOAD["mejoras"]
    assert written["enfoque_proxima_sesion"] == "foco"
    assert [r["instancias"] for r in written["errores"]] == [
        r["instancias"] for r in V2_PAYLOAD["errores"]
    ]


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_writes_a_provenance_sidecar(mock_cls: MagicMock, tmp_path: Path) -> None:
    """A backfilled id saw only (patron, tipo, instancias), never the
    transcript — weaker evidence than a native one, and WS2 needs to be able
    to tell them apart."""
    mock_cls.return_value.messages.parse.return_value = _assignment(
        (0, "calco-hacer-sentido"), (1, "por-vs-para")
    )
    p = _session(tmp_path, "2026-08-01-monologo", V2_PAYLOAD)

    backfill.backfill_file(p, _config(), dry_run=False, today=TODAY)

    sidecar = json.loads((p.parent / "backfill.json").read_text())
    assert sidecar["backfill_version"] == backfill.BACKFILL_VERSION
    assert sidecar["fecha"] == "2026-08-10"
    assert [a["pattern_id"] for a in sidecar["asignaciones"]] == [
        "calco-hacer-sentido",
        "por-vs-para",
    ]


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_misaligned_indices_retry_then_fail(
    mock_cls: MagicMock, tmp_path: Path
) -> None:
    """A dropped row would silently shift every id after it, so indices are
    validated as a permutation rather than trusted positionally."""
    client = mock_cls.return_value
    client.messages.parse.return_value = _assignment((0, "por-vs-para"))  # 2 rows
    p = _session(tmp_path, "2026-08-01-monologo", V2_PAYLOAD)

    out = backfill.backfill_file(p, _config(), dry_run=False, today=TODAY)

    assert out.status == "failed"
    assert "one assignment per row" in out.detail
    assert client.messages.parse.call_count == 2
    assert "pattern_id" not in json.loads(p.read_text())["errores"][0]


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_misalignment_recovers_on_retry(mock_cls: MagicMock, tmp_path: Path) -> None:
    client = mock_cls.return_value
    client.messages.parse.side_effect = [
        _assignment((0, "por-vs-para")),
        _assignment((0, "calco-hacer-sentido"), (1, "por-vs-para")),
    ]
    p = _session(tmp_path, "2026-08-01-monologo", V2_PAYLOAD)

    out = backfill.backfill_file(p, _config(), dry_run=False, today=TODAY)

    assert out.status == "assigned"
    assert client.messages.parse.call_count == 2


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_duplicate_ids_trigger_a_retry(mock_cls: MagicMock, tmp_path: Path) -> None:
    """Observed for real: a run assigned `autocorreccion-excesiva` to both the
    self-correction row and a double-negation row."""
    client = mock_cls.return_value
    client.messages.parse.side_effect = [
        _assignment((0, "concordancia-genero"), (1, "concordancia-genero")),
        _assignment((0, "calco-hacer-sentido"), (1, "por-vs-para")),
    ]
    p = _session(tmp_path, "2026-08-01-monologo", V2_PAYLOAD)

    out = backfill.backfill_file(p, _config(), dry_run=False, today=TODAY)

    assert out.status == "assigned"
    assert client.messages.parse.call_count == 2
    assert json.loads((p.parent / "backfill.json").read_text())["duplicados"] == []


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_unresolved_duplicates_are_recorded_not_refused(
    mock_cls: MagicMock, tmp_path: Path
) -> None:
    """Refusing would leave a legacy session invisible to tracking entirely —
    worse than one imperfect id the sidecar flags for review."""
    client = mock_cls.return_value
    client.messages.parse.return_value = _assignment(
        (0, "concordancia-genero"), (1, "concordancia-genero")
    )
    p = _session(tmp_path, "2026-08-01-monologo", V2_PAYLOAD)

    out = backfill.backfill_file(p, _config(), dry_run=False, today=TODAY)

    assert out.status == "assigned"
    assert client.messages.parse.call_count == 2
    sidecar = json.loads((p.parent / "backfill.json").read_text())
    assert sidecar["duplicados"] == ["concordancia-genero"]


def test_duplicate_ids_ignores_otro() -> None:
    assert backfill.duplicate_ids(["otro", "otro", "por-vs-para"]) == []
    assert backfill.duplicate_ids(["por-vs-para", "por-vs-para"]) == ["por-vs-para"]


# ── dry run ────────────────────────────────────────────────────────────────


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_dry_run_writes_nothing(mock_cls: MagicMock, tmp_path: Path) -> None:
    mock_cls.return_value.messages.parse.return_value = _assignment(
        (0, "calco-hacer-sentido"), (1, "por-vs-para")
    )
    p = _session(tmp_path, "2026-08-01-monologo", V2_PAYLOAD)
    before = p.read_text()

    out = backfill.backfill_file(p, _config(), dry_run=True, today=TODAY)

    assert out.status == "assigned" and out.assigned == 2
    assert p.read_text() == before
    assert not (p.parent / "backfill.json").exists()


# ── walking the corpus ─────────────────────────────────────────────────────


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_a_malformed_session_fails_alone(
    mock_cls: MagicMock, tmp_path: Path
) -> None:
    """One corrupt session must not strand the rest of the corpus unassigned."""
    mock_cls.return_value.messages.parse.return_value = _assignment(
        (0, "calco-hacer-sentido"), (1, "por-vs-para")
    )
    _session(tmp_path, "2026-08-01-monologo", "{not json at all")
    _session(tmp_path, "2026-08-02-monologo", {"errores": "not a list"})
    good = _session(tmp_path, "2026-08-03-monologo", V2_PAYLOAD)

    outcomes = backfill.backfill_all(
        tmp_path, _config(), dry_run=False, today=TODAY
    )

    by_name = {o.path.parent.name: o for o in outcomes}
    assert by_name["2026-08-01-monologo"].status == "failed"
    assert by_name["2026-08-02-monologo"].status == "failed"
    assert by_name["2026-08-03-monologo"].status == "assigned"
    assert "pattern_id" in json.loads(good.read_text())["errores"][0]


def test_find_examiner_files_ignores_other_artifacts(tmp_path: Path) -> None:
    p = _session(tmp_path, "2026-08-01-monologo", V2_PAYLOAD)
    (p.parent / "whisper.json").write_text("{}")
    (p.parent / "metrics.json").write_text("{}")
    assert backfill.find_examiner_files(tmp_path) == [p]


def test_empty_corpus_is_not_an_error(tmp_path: Path) -> None:
    assert backfill.backfill_all(tmp_path, _config(), dry_run=False, today=TODAY) == []


# ── prompt ─────────────────────────────────────────────────────────────────


def test_prompt_carries_vocabulary_and_rows() -> None:
    prompt = backfill.build_prompt(V2_PAYLOAD["errores"])
    assert "{vocabulario}" not in prompt and "{filas}" not in prompt
    assert "`por-vs-para`" in prompt  # vocabulary rendered
    assert "`otro`" in prompt
    assert "eso no hace sentido" in prompt  # instances anchor the choice
    assert "0. tipo=calco" in prompt and "1. tipo=gramatica" in prompt
    # It classifies existing findings; it must not re-judge them.
    assert "No busques errores nuevos" in prompt


@patch.dict("os.environ", {}, clear=True)
def test_missing_api_key_is_reported() -> None:
    with pytest.raises(Exception, match="ANTHROPIC_API_KEY"):
        backfill.assign(V2_PAYLOAD["errores"], _config())
