"""CLI orchestration tests (spec §1): output destination resolution, and the
gates on the `progreso` command.

The vault is one destination among several, not a prerequisite — a run with
nothing configured still has somewhere to write.
"""

import csv
import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from analiza import note
from analiza.cli import _resolve_base, app
from analiza.config import Config
from analiza.narrativa import ProgresoResult


def test_nothing_configured_defaults_into_the_repo() -> None:
    """No vault, no --out, no config: writes flat to the default dir."""
    assert _resolve_base(None, None, Config()) == note.DEFAULT_OUTPUT_DIR
    assert "Español" not in str(note.DEFAULT_OUTPUT_DIR)


def test_out_flag_writes_flat() -> None:
    assert _resolve_base(None, Path("/o"), Config()) == Path("/o")


def test_config_output_dir_used_when_no_flag() -> None:
    cfg = Config(output_dir=Path("/cfg-out"))
    assert _resolve_base(None, None, cfg) == Path("/cfg-out")


def test_out_flag_overrides_config_output_dir() -> None:
    cfg = Config(output_dir=Path("/cfg-out"))
    assert _resolve_base(None, Path("/flag"), cfg) == Path("/flag")


def test_vault_flag_selects_nested_layout() -> None:
    assert _resolve_base(Path("/v"), None, Config()) == Path("/v/Español")


def test_config_vault_path_selects_nested_layout() -> None:
    cfg = Config(vault_path=Path("/cfg-vault"))
    assert _resolve_base(None, None, cfg) == Path("/cfg-vault/Español")


def test_vault_wins_over_out() -> None:
    """--vault is the more specific intent: it also picks the layout."""
    assert _resolve_base(Path("/v"), Path("/o"), Config()) == Path("/v/Español")


def test_vault_flag_overrides_config_vault_path() -> None:
    cfg = Config(vault_path=Path("/cfg-vault"))
    assert _resolve_base(Path("/flag"), None, cfg) == Path("/flag/Español")


def test_config_vault_wins_over_out_flag() -> None:
    """A configured vault still selects the vault layout — --out does not
    silently downgrade it to flat, it is simply lower precedence."""
    cfg = Config(vault_path=Path("/cfg-vault"))
    assert _resolve_base(None, Path("/o"), cfg) == Path("/cfg-vault/Español")


# ── progreso: the narrative gate is a spend gate too ────────────────────────

HOY = dt.date.today()

LECTURA = ProgresoResult(
    lectura="Vas más rápido.",
    patrones_prioritarios=[],
    cautelas=[],
    enfoque_proxima_sesion="Sigue.",
)


def _corpus(base: Path, n: int) -> None:
    """`n` recorded sessions, each with a stored examiner artifact."""
    rows = []
    for i in range(1, n + 1):
        fecha = f"2026-08-{i:02d}"
        rows.append(
            {
                **{c: "" for c in note.STATS_COLUMNS},
                "date": fecha, "ejercicio": "monologo", "duration_s": "600",
                "wpm_gross": str(50 + i), "pauses_n": "30", "mtld": "40",
                "whisper_model": "small", "prompt_version": "examiner_v3",
                "vocab_version": "vocab_v1",
            }
        )
        raw = base / "analiza-raw" / f"{fecha}-monologo"
        raw.mkdir(parents=True)
        (raw / "examiner.json").write_text(
            json.dumps(
                {"errores": [{"pattern_id": "por-vs-para", "instancias": ["a"]}]}
            )
        )
    with (base / "analiza-stats.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=note.STATS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _raw_progreso(base: Path) -> Path:
    return base / "analiza-raw" / f"progreso-{HOY.isoformat()}"


@patch("analiza.cli.config_mod.load_config", return_value=Config())
@patch("analiza.narrativa.run_progreso")
def test_progreso_below_the_gate_writes_numbers_and_calls_nothing(
    run: MagicMock, _cfg: MagicMock, tmp_path: Path
) -> None:
    """Declining to report is the feature — and it must not cost an API call
    to decline."""
    _corpus(tmp_path, 3)
    result = CliRunner().invoke(app, ["progreso", "--out", str(tmp_path)])

    assert result.exit_code == 0
    run.assert_not_called()
    assert (_raw_progreso(tmp_path) / "stats.json").exists()
    assert not (_raw_progreso(tmp_path) / "progreso.json").exists()
    assert "sin lectura" in result.output


@patch("analiza.cli.config_mod.load_config", return_value=Config())
@patch("analiza.narrativa.run_progreso")
def test_progreso_no_llm_skips_the_pass_above_the_gate(
    run: MagicMock, _cfg: MagicMock, tmp_path: Path
) -> None:
    _corpus(tmp_path, 10)
    result = CliRunner().invoke(
        app, ["progreso", "--out", str(tmp_path), "--no-llm"]
    )

    assert result.exit_code == 0
    run.assert_not_called()
    assert not (_raw_progreso(tmp_path) / "progreso.json").exists()


@patch("analiza.cli.config_mod.load_config", return_value=Config())
@patch("analiza.narrativa.run_progreso", return_value=LECTURA)
def test_progreso_records_the_prompt_version_with_the_prose(
    run: MagicMock, _cfg: MagicMock, tmp_path: Path
) -> None:
    """A prompt change breaks comparability between two reports exactly as it
    does between two sessions, so the version travels with the output."""
    _corpus(tmp_path, 10)
    result = CliRunner().invoke(app, ["progreso", "--out", str(tmp_path)])

    assert result.exit_code == 0
    run.assert_called_once()
    # It was handed the aggregation, not sessions or transcripts.
    assert run.call_args.args[0].sesiones_n == 10

    envelope = json.loads((_raw_progreso(tmp_path) / "progreso.json").read_text())
    assert envelope["prompt_version"] == "progreso_v1"
    assert envelope["lectura"]["lectura"] == "Vas más rápido."
    nota = next((tmp_path / "Progreso").glob("*.md")).read_text()
    assert "_progreso_version: progreso_v1_" in nota


@patch("analiza.cli.config_mod.load_config", return_value=Config())
@patch("analiza.narrativa.run_progreso")
def test_progreso_survives_a_failed_narrative(
    run: MagicMock, _cfg: MagicMock, tmp_path: Path
) -> None:
    """The numbers are the durable part: a failed reading downgrades the note,
    it does not lose the report."""
    from analiza.examiner import ExaminerError

    run.side_effect = ExaminerError("boom")
    _corpus(tmp_path, 10)
    result = CliRunner().invoke(app, ["progreso", "--out", str(tmp_path)])

    assert result.exit_code == 4
    assert (_raw_progreso(tmp_path) / "stats.json").exists()
    assert not (_raw_progreso(tmp_path) / "progreso.json").exists()
    assert next((tmp_path / "Progreso").glob("*.md")).exists()


@patch("analiza.cli.config_mod.load_config", return_value=Config())
def test_progreso_without_a_corpus_exits_distinctly(
    _cfg: MagicMock, tmp_path: Path
) -> None:
    result = CliRunner().invoke(app, ["progreso", "--out", str(tmp_path)])
    assert result.exit_code == 5
