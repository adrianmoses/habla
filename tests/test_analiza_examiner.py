"""Examiner tests (spec §2E): prompt build, structured outputs, one retry."""

import importlib.resources
import json
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from analiza import examiner
from analiza.config import Config
from analiza.examiner import ExaminerResult
from analiza.patrones_b2 import PATRON_IDS, PATRONES, PATRONES_POR_ID, PatternId

VALID_PAYLOAD = {
    "puntuaciones": [
        {"criterio": c, "puntuacion": 2, "justificacion": "ok"}
        for c in ("coherencia", "fluidez", "correccion", "alcance")
    ],
    "errores": [
        {
            "pattern_id": "calco-hacer-sentido",
            "tipo": "calco",
            "patron": "hacer sentido",
            "deberia_ser": "tener sentido",
            "por_que": "traducción literal de «make sense»",
            "instancias": ["eso no hace sentido", "no hace sentido para mí"],
        },
        {
            "pattern_id": "por-vs-para",
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


def test_prompt_asset_carries_v3_contract() -> None:
    """PROMPT_VERSION and the prompt asset must not drift apart: the template
    has to name the matching schema and state the labeling rules."""
    template = examiner.load_prompt_template()
    assert examiner.PROMPT_VERSION == "examiner_v3"
    assert "output_schema_v3.json" in template
    assert "{pattern_id, tipo, patron, deberia_ser, por_que, instancias}" in template
    # calco wins ties, sorts first, and loanwords are explicitly out of scope.
    assert "categoría prioritaria" in template
    assert "No reportes préstamos del inglés" in template
    for tipo in ("calco", "gramatica", "lexico", "registro"):
        assert tipo in template


def test_prompt_carries_the_whole_vocabulary() -> None:
    """The model can only pick an id it was shown. Rendering from patrones_b2
    (rather than copying the list into the asset) is what keeps the enum the
    API enforces and the list the model reads from drifting apart."""
    prompt = examiner.build_prompt(
        transcript="hola", metrics={}, tema=None, ejercicio="monologo",
        low_conf_hints=[], subjunctive_connectors=[],
    )
    assert "{vocabulario}" not in prompt
    for patron in PATRONES:
        assert f"`{patron.id}`" in prompt, f"{patron.id} never reaches the model"
    # `otro` has no Patron entry, so the asset must introduce it itself.
    assert "`otro`" in prompt


def test_build_prompt_empty_optionals() -> None:
    prompt = examiner.build_prompt(
        transcript="hola", metrics={}, tema=None, ejercicio="monologo",
        low_conf_hints=[], subjunctive_connectors=[],
    )
    assert "(sin tema)" in prompt
    assert "(ninguno)" in prompt


def _parsed(payload: dict | None = None, stop_reason: str = "end_turn") -> MagicMock:
    """A messages.parse() result: the API guarantees the shape, so the SDK
    hands back an already-validated ExaminerResult (None if there was no text
    block at all)."""
    response = MagicMock()
    response.parsed_output = (
        None if payload is None else ExaminerResult.model_validate(payload)
    )
    response.stop_reason = stop_reason
    return response


def _validation_error() -> ValidationError:
    """A real pydantic error, as parse() raises when a count/range constraint
    is violated — those are description hints to the API, not enforced by it."""
    try:
        ExaminerResult.model_validate({})
    except ValidationError as e:
        return e
    raise AssertionError("expected ValidationError")


def _config() -> Config:
    return Config()


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_requests_structured_output(mock_cls: MagicMock) -> None:
    """The schema is passed to the API, so the shape can't come back wrong."""
    client = mock_cls.return_value
    client.messages.parse.return_value = _parsed(VALID_PAYLOAD)
    result = examiner.run_examiner("prompt", _config())
    assert result.enfoque_proxima_sesion == "foco"
    assert client.messages.parse.call_count == 1
    assert client.messages.create.call_count == 0  # no unconstrained call path
    assert client.messages.parse.call_args.kwargs["output_format"] is (
        examiner.ExaminerResult
    )


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_groups_errors_by_pattern(mock_cls: MagicMock) -> None:
    """Instances live inside a pattern row, and calcos are separable."""
    client = mock_cls.return_value
    client.messages.parse.return_value = _parsed(VALID_PAYLOAD)
    result = examiner.run_examiner("prompt", _config())
    assert len(result.errores) == 2
    assert [e.tipo for e in result.calcos] == ["calco"]
    assert result.calcos[0].instancias == [
        "eso no hace sentido",
        "no hace sentido para mí",
    ]
    assert [e.patron for e in result.otros_errores] == ["por vs para"]


def test_run_examiner_enum_is_enforced_by_the_schema() -> None:
    """An off-enum tipo (e.g. the dropped "anglicismo") can no longer reach the
    client: the API constrains generation to the enum. The model-side guard
    stays as the backstop for any path that bypasses structured outputs."""
    bad = {**VALID_PAYLOAD, "errores": [{**VALID_PAYLOAD["errores"][0],
                                         "tipo": "anglicismo"}]}
    with pytest.raises(ValidationError):
        ExaminerResult.model_validate(bad)


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_retries_once_then_succeeds(mock_cls: MagicMock) -> None:
    """Count/range constraints are description hints to the API, not enforced
    by it — a violation surfaces as a pydantic error from parse(), and that is
    what the single retry is for."""
    client = mock_cls.return_value
    client.messages.parse.side_effect = [
        _validation_error(),
        _parsed(VALID_PAYLOAD),
    ]
    result = examiner.run_examiner("prompt", _config())
    assert result.enfoque_proxima_sesion == "foco"
    assert client.messages.parse.call_count == 2
    retry_prompt = client.messages.parse.call_args_list[1].kwargs["messages"][0][
        "content"
    ]
    assert "no cumplió el esquema" in retry_prompt


def test_vocabulary_and_literal_agree() -> None:
    """PATRONES describes every id except `otro`, with no duplicates. mypy
    catches a typo'd id in PATRONES; this catches the other direction — an id
    added to the Literal and never described, which the model could then be
    asked to emit with no idea what it means."""
    literal_ids = set(get_args(PatternId))
    described = [p.id for p in PATRONES]
    assert len(described) == len(set(described)), "duplicate id in PATRONES"
    assert literal_ids - set(described) == {"otro"}
    assert set(described) - literal_ids == set()


def test_every_patron_is_well_formed() -> None:
    """`ejemplos` must be a non-empty tuple of strings. A single-element entry
    written `("...")` instead of `("...",)` is a string, and would render into
    the prompt one character at a time — mypy catches it, but CI's mypy scope
    does not cover analiza/, so this is the guard that actually runs."""
    for p in PATRONES:
        assert isinstance(p.ejemplos, tuple), f"{p.id}: ejemplos is not a tuple"
        assert p.ejemplos, f"{p.id}: no ejemplos to anchor the choice"
        assert all(isinstance(e, str) and e for e in p.ejemplos), f"{p.id}: bad ejemplo"
        assert p.etiqueta.strip(), f"{p.id}: empty etiqueta"


def test_escape_hatch_is_excluded_from_tracking() -> None:
    """`otro` is a bucket, not a pattern. Letting it into PATRON_IDS would make
    every unclassifiable finding look like one recurring fault."""
    assert "otro" not in PATRON_IDS
    assert "otro" not in PATRONES_POR_ID


def test_pattern_id_is_required_and_enum_constrained() -> None:
    row = {
        "tipo": "gramatica", "patron": "x", "deberia_ser": "y",
        "por_que": "z", "instancias": ["w"],
    }
    with pytest.raises(ValidationError):  # missing
        examiner.ErrorRow.model_validate(row)
    with pytest.raises(ValidationError):  # off-vocabulary
        examiner.ErrorRow.model_validate({**row, "pattern_id": "inventado"})
    assert examiner.ErrorRow.model_validate(
        {**row, "pattern_id": "por-vs-para"}
    ).pattern_id == "por-vs-para"


def test_repeated_pattern_id_is_rejected() -> None:
    """One row per fault is the premise of pattern grouping, so two rows
    sharing an id means one is mis-keyed. Observed for real: a backfill run
    assigned `autocorreccion-excesiva` to both the self-correction row and a
    double-negation row."""
    rows = VALID_PAYLOAD["errores"]
    dup = [{**rows[0]}, {**rows[1], "pattern_id": rows[0]["pattern_id"]}]
    with pytest.raises(ValidationError, match="repeated across rows"):
        ExaminerResult.model_validate({**VALID_PAYLOAD, "errores": dup})


def test_repeated_otro_is_allowed() -> None:
    """`otro` is a bucket, not a fault — several unrelated findings land there
    legitimately, and it is excluded from recurrence tracking anyway."""
    rows = VALID_PAYLOAD["errores"]
    both_otro = [{**rows[0], "pattern_id": "otro"}, {**rows[1], "pattern_id": "otro"}]
    result = ExaminerResult.model_validate({**VALID_PAYLOAD, "errores": both_otro})
    assert [e.pattern_id for e in result.errores] == ["otro", "otro"]


def test_documented_schema_has_not_drifted_from_the_vocabulary() -> None:
    """output_schema_v3.json is documentation — structured outputs send the
    pydantic-derived schema, not this file — but the prompt names it, so a
    stale enum here is a contradictory instruction to the model."""
    doc = json.loads(
        (
            importlib.resources.files("analiza")
            / "schemas"
            / "output_schema_v3.json"
        ).read_text()
    )
    props = doc["properties"]["errores"]["items"]
    assert set(props["properties"]["pattern_id"]["enum"]) == set(get_args(PatternId))
    assert "pattern_id" in props["required"]


def test_unenforced_constraints_become_description_hints() -> None:
    """Structured outputs reject count/range constraints, so the SDK folds them
    into each field's description — the model still sees them. If this stops
    holding, those limits are silently unenforced end to end."""
    from anthropic.lib._parse._transform import transform_schema

    schema = transform_schema(ExaminerResult.model_json_schema())
    assert "maxItems: 10" in schema["properties"]["errores"]["description"]
    assert (
        "minimum: 1"
        in schema["$defs"]["Puntuacion"]["properties"]["puntuacion"]["description"]
    )
    # instancias' minItems IS supported natively, so it stays a real constraint.
    assert schema["$defs"]["ErrorRow"]["properties"]["instancias"]["minItems"] == 1


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_no_text_block_fails_fast(mock_cls: MagicMock) -> None:
    """All budget spent thinking → no text block. Retrying burns another full
    call on the same wall, so fail immediately with an actionable message."""
    client = mock_cls.return_value
    client.messages.parse.return_value = _parsed(None, stop_reason="max_tokens")

    with pytest.raises(examiner.ExaminerError, match="no text block"):
        examiner.run_examiner("prompt", _config())
    assert client.messages.parse.call_count == 1


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_requests_enough_budget_for_thinking(
    mock_cls: MagicMock,
) -> None:
    """max_tokens covers thinking + text on models that think by default."""
    client = mock_cls.return_value
    client.messages.parse.return_value = _parsed(VALID_PAYLOAD)
    examiner.run_examiner("prompt", _config())
    assert client.messages.parse.call_args.kwargs["max_tokens"] == examiner.MAX_TOKENS
    assert examiner.MAX_TOKENS >= 16000


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_examiner_fails_after_second_violation(mock_cls: MagicMock) -> None:
    client = mock_cls.return_value
    client.messages.parse.side_effect = [_validation_error(), _validation_error()]
    with pytest.raises(examiner.ExaminerError, match="after retry"):
        examiner.run_examiner("prompt", _config())
    assert client.messages.parse.call_count == 2


@patch.dict("os.environ", {}, clear=True)
def test_run_examiner_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(examiner.ExaminerError, match="ANTHROPIC_API_KEY"):
        examiner.run_examiner("prompt", _config())
