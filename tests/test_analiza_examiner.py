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
    "errores": [],
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
