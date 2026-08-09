"""Examiner tests (spec §2E): prompt build and retry-on-schema-violation."""

import json
from unittest.mock import MagicMock, patch

import pytest

from analiza import examiner
from analiza.config import Config

VALID_PAYLOAD = {
    "puntuaciones": [
        {"criterio": c, "puntuacion": 2, "justificacion": "ok"}
        for c in ("coherencia", "fluidez", "correccion", "alcance")
    ],
    "errores": [
        {
            "tipo": "calco",
            "patron": "hacer sentido",
            "deberia_ser": "tener sentido",
            "por_que": "traducción literal de «make sense»",
            "instancias": ["eso no hace sentido", "no hace sentido para mí"],
        },
        {
            "tipo": "gramatica",
            "patron": "por vs para",
            "deberia_ser": "para",
            "por_que": "finalidad, no causa",
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


def test_build_prompt_fills_all_placeholders() -> None:
    prompt = examiner.build_prompt(
        transcript="hola mundo",
        metrics={"wpm_gross": 90.0},
        tema="viajes",
        ejercicio="monologo",
        low_conf_hints=[(1.0, 2.5)],
        subjunctive_connectors=["a menos que"],
    )
    assert "{transcript}" not in prompt and "hola mundo" in prompt
    assert "{metrics_json}" not in prompt and '"wpm_gross": 90.0' in prompt
    assert "1.0s–2.5s" in prompt
    assert "a menos que" in prompt
    # Literal braces of the schema description must survive (no str.format).
    assert "{criterio, puntuacion, justificacion}" in prompt


def test_prompt_asset_carries_v2_contract() -> None:
    """PROMPT_VERSION and the prompt asset must not drift apart: the template
    has to name the matching schema and state the calco labeling rules."""
    template = examiner.load_prompt_template()
    assert examiner.PROMPT_VERSION == "examiner_v2"
    assert "output_schema_v2.json" in template
    assert "{tipo, patron, deberia_ser, por_que, instancias}" in template
    # calco wins ties, sorts first, and loanwords are explicitly out of scope.
    assert "categoría prioritaria" in template
    assert "No reportes préstamos del inglés" in template
    for tipo in ("calco", "gramatica", "lexico", "registro"):
        assert tipo in template


def test_build_prompt_empty_optionals() -> None:
    prompt = examiner.build_prompt(
        transcript="hola", metrics={}, tema=None, ejercicio="monologo",
        low_conf_hints=[], subjunctive_connectors=[],
    )
    assert "(sin tema)" in prompt
    assert "(ninguno)" in prompt


def _response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _config() -> Config:
    return Config()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_parses_valid_response(mock_cls: MagicMock) -> None:
    client = mock_cls.return_value
    client.messages.create.return_value = _response(json.dumps(VALID_PAYLOAD))
    result = examiner.run_examiner("prompt", _config())
    assert result.enfoque_proxima_sesion == "foco"
    assert client.messages.create.call_count == 1


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_groups_errors_by_pattern(mock_cls: MagicMock) -> None:
    """Instances live inside a pattern row, and calcos are separable."""
    client = mock_cls.return_value
    client.messages.create.return_value = _response(json.dumps(VALID_PAYLOAD))
    result = examiner.run_examiner("prompt", _config())
    assert len(result.errores) == 2
    assert [e.tipo for e in result.calcos] == ["calco"]
    assert result.calcos[0].instancias == [
        "eso no hace sentido",
        "no hace sentido para mí",
    ]
    assert [e.patron for e in result.otros_errores] == ["por vs para"]


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_retries_on_unknown_tipo(mock_cls: MagicMock) -> None:
    """An off-enum tipo (e.g. the dropped "anglicismo") must not slip through."""
    bad = {**VALID_PAYLOAD, "errores": [{**VALID_PAYLOAD["errores"][0],
                                         "tipo": "anglicismo"}]}
    client = mock_cls.return_value
    client.messages.create.side_effect = [
        _response(json.dumps(bad)),
        _response(json.dumps(VALID_PAYLOAD)),
    ]
    result = examiner.run_examiner("prompt", _config())
    assert client.messages.create.call_count == 2
    assert [e.tipo for e in result.errores] == ["calco", "gramatica"]


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_retries_on_empty_instancias(mock_cls: MagicMock) -> None:
    """A pattern with no occurrence is meaningless — min_length=1 rejects it."""
    bad = {**VALID_PAYLOAD, "errores": [{**VALID_PAYLOAD["errores"][0],
                                         "instancias": []}]}
    client = mock_cls.return_value
    client.messages.create.side_effect = [
        _response(json.dumps(bad)),
        _response(json.dumps(VALID_PAYLOAD)),
    ]
    examiner.run_examiner("prompt", _config())
    assert client.messages.create.call_count == 2


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_strips_code_fences(mock_cls: MagicMock) -> None:
    client = mock_cls.return_value
    client.messages.create.return_value = _response(
        f"```json\n{json.dumps(VALID_PAYLOAD)}\n```"
    )
    assert examiner.run_examiner("prompt", _config()).enfoque_proxima_sesion == "foco"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_retries_once_then_succeeds(mock_cls: MagicMock) -> None:
    client = mock_cls.return_value
    client.messages.create.side_effect = [
        _response("no es json"),
        _response(json.dumps(VALID_PAYLOAD)),
    ]
    result = examiner.run_examiner("prompt", _config())
    assert result.enfoque_proxima_sesion == "foco"
    assert client.messages.create.call_count == 2
    retry_prompt = client.messages.create.call_args_list[1].kwargs["messages"][0][
        "content"
    ]
    assert "no cumplió el esquema" in retry_prompt


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_fails_after_second_violation(mock_cls: MagicMock) -> None:
    client = mock_cls.return_value
    client.messages.create.return_value = _response("sigo sin ser json")
    with pytest.raises(examiner.ExaminerError):
        examiner.run_examiner("prompt", _config())
    assert client.messages.create.call_count == 2


@patch.dict("os.environ", {}, clear=True)
def test_run_examiner_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(examiner.ExaminerError, match="ANTHROPIC_API_KEY"):
        examiner.run_examiner("prompt", _config())
