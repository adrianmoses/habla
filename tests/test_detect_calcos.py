import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from scripts import detect_calcos
from scripts.detect_calcos import Calco, CalcoError, CalcoReport


def _report(**overrides) -> CalcoReport:
    calco = Calco(
        calco="aplicar para",
        origen_ingles="to apply for",
        fragmentos=["apliqué para el trabajo"],
        castellano="presentarme al puesto",
        madrileno=None,
        por_que="'apply for' se dice 'presentarse a' o 'echar la solicitud'.",
    )
    fields = {"calcos": [calco], "resumen": "Calcos de régimen.", **overrides}
    return CalcoReport(**fields)


def _fake_client(monkeypatch, parse):
    """Install a fake Anthropic client and return the captured-kwargs dict."""
    captured: dict = {}

    class FakeMessages:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return parse(**kwargs)

    client = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(detect_calcos, "Anthropic", lambda **kwargs: client)
    return captured


def _validation_error() -> ValidationError:
    try:
        CalcoReport.model_validate({"calcos": []})  # `resumen` missing
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


def test_detect_calcos_sends_the_text_under_the_schema(monkeypatch) -> None:
    report = _report()
    captured = _fake_client(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(parsed_output=report, stop_reason="end_turn"),
    )

    result = detect_calcos.detect_calcos("Apliqué para el trabajo", "test-key")

    assert result is report
    assert captured["model"] == detect_calcos.MODEL
    assert captured["output_format"] is CalcoReport
    assert "Apliqué para el trabajo" in captured["messages"][0]["content"]


def test_detect_calcos_retries_once_on_schema_violation(monkeypatch) -> None:
    """A calque with no occurrences is the one rule the API cannot enforce, so
    pydantic raises it and the retry has to carry the error back."""
    report = _report()
    prompts: list[str] = []

    def parse(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        if len(prompts) == 1:
            raise _validation_error()
        return SimpleNamespace(parsed_output=report, stop_reason="end_turn")

    _fake_client(monkeypatch, parse)

    assert detect_calcos.detect_calcos("texto", "test-key") is report
    assert len(prompts) == 2
    assert "no cumplió el esquema" in prompts[1]


def test_detect_calcos_raises_after_a_failed_retry(monkeypatch) -> None:
    def parse(**kwargs):
        raise _validation_error()

    _fake_client(monkeypatch, parse)

    with pytest.raises(CalcoError, match="schema validation failed after retry"):
        detect_calcos.detect_calcos("texto", "test-key")


def test_detect_calcos_reports_a_budget_spent_on_thinking(monkeypatch) -> None:
    """No text block at all: a retry hits the same wall, so say what to raise."""
    _fake_client(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(parsed_output=None, stop_reason="max_tokens"),
    )

    with pytest.raises(CalcoError, match="MAX_TOKENS"):
        detect_calcos.detect_calcos("texto", "test-key")


def test_render_report_omits_madrileno_when_it_matches_castellano() -> None:
    rendered = detect_calcos.render_report(_report())

    assert "castellano: presentarme al puesto" in rendered
    assert "madrileño" not in rendered


def test_render_report_shows_madrileno_when_it_differs() -> None:
    calco = _report().calcos[0].model_copy(update={"madrileno": "echar el CV"})
    rendered = detect_calcos.render_report(_report(calcos=[calco]))

    assert "madrileño:  echar el CV" in rendered


def test_render_report_groups_every_occurrence_under_one_calque() -> None:
    calco = _report().calcos[0].model_copy(
        update={"fragmentos": ["apliqué para el trabajo", "aplicar para otro puesto"]}
    )
    rendered = detect_calcos.render_report(_report(calcos=[calco]))

    assert rendered.startswith("1 calco, 2 apariciones.")
    assert '· "apliqué para el trabajo"' in rendered
    assert '· "aplicar para otro puesto"' in rendered


def test_render_report_handles_a_clean_text() -> None:
    rendered = detect_calcos.render_report(
        CalcoReport(calcos=[], resumen="Sin calcos visibles.")
    )

    assert "Ningún calco visible" in rendered
    assert "Resumen: Sin calcos visibles." in rendered


def test_resolve_text_reads_a_file(tmp_path: Path) -> None:
    source = tmp_path / "texto.txt"
    source.write_text("Apliqué para el trabajo\n", encoding="utf-8")

    assert (
        detect_calcos.resolve_text(source, None, io.StringIO())
        == "Apliqué para el trabajo"
    )


def test_resolve_text_reads_stdin_for_a_dash() -> None:
    stdin = io.StringIO("Eso no hace sentido")

    assert detect_calcos.resolve_text(Path("-"), None, stdin) == "Eso no hace sentido"


def test_resolve_text_rejects_a_file_and_text_together(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not both"):
        detect_calcos.resolve_text(tmp_path / "texto.txt", "hola", io.StringIO())


def test_resolve_text_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        detect_calcos.resolve_text(None, "   \n ", io.StringIO())


def test_main_exits_2_without_an_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(detect_calcos.API_KEY_ENV, raising=False)
    monkeypatch.setattr(detect_calcos, "load_dotenv", lambda path: None)

    argv = ["--text", "hola", "--env-file", str(tmp_path / ".env")]

    assert detect_calcos.main(argv) == 2


def test_main_writes_json_to_the_output_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(detect_calcos.API_KEY_ENV, "test-key")
    monkeypatch.setattr(detect_calcos, "load_dotenv", lambda path: None)
    monkeypatch.setattr(
        detect_calcos, "detect_calcos", lambda text, api_key, model: _report()
    )
    destination = tmp_path / "calcos.json"

    code = detect_calcos.main(
        ["--text", "Apliqué para el trabajo", "--json", "-o", str(destination)]
    )

    assert code == 0
    assert '"calco": "aplicar para"' in destination.read_text(encoding="utf-8")
