"""Narrative pass tests (spec 034 WS3).

What matters here is the boundary, not the prose: the model must receive the
aggregation and nothing else, and must not be able to smuggle a fault into the
report that the corpus never recorded.
"""

import datetime as dt
import importlib.resources
import json
from typing import Any, get_args
from unittest.mock import MagicMock, patch

import pytest

from analiza import narrativa
from analiza.config import Config, ProgresoThresholds
from analiza.narrativa import ProgresoResult
from analiza.patrones_b2 import PatternId
from analiza.progreso import Sesion, aggregate

HOY = dt.date(2026, 9, 1)
CONFIG = Config()

VALID_PAYLOAD: dict[str, Any] = {
    "lectura": "Has ganado velocidad y el subjuntivo sigue fallando.",
    "patrones_prioritarios": [
        {"pattern_id": "por-vs-para", "por_que": "6 instancias en 4 sesiones"}
    ],
    "cautelas": ["Una sesión de baja confianza."],
    "enfoque_proxima_sesion": "Contrastar por/para en frases propias.",
}


def _stats(patrones: dict[str, int] | None = None, n: int = 10):
    """An aggregation over `n` sessions, all carrying the same faults."""
    sesiones = [
        Sesion(
            fecha=dt.date(2026, 8, i),
            ejercicio="monologo",
            metricas={"wpm_gross": 55.0 + i},
            whisper_model="small",
            prompt_version="examiner_v3",
            vocab_version="vocab_v1",
            patrones={"por-vs-para": 2} if patrones is None else patrones,
        )
        for i in range(1, n + 1)
    ]
    return aggregate(sesiones, hoy=HOY, parametros=ProgresoThresholds())


def _parsed(payload: dict[str, Any] | None = None, stop_reason: str = "end_turn"):
    """A messages.parse() result. parsed_output is None when the model spent
    its whole budget thinking and returned no text block."""
    response = MagicMock()
    response.parsed_output = (
        ProgresoResult.model_validate(payload) if payload is not None else None
    )
    response.stop_reason = stop_reason
    return response


# ── The input boundary ──────────────────────────────────────────────────────


def test_the_prompt_carries_the_aggregation_and_nothing_else() -> None:
    """The governing principle of the track: the model judges numbers that
    were counted deterministically, and never sees a transcript."""
    stats = _stats()
    prompt = narrativa.build_prompt(stats)
    assert "{stats_json}" not in prompt
    assert '"pattern_id": "por-vs-para"' in prompt
    assert '"sesiones_n": 10' in prompt
    # Literal braces of the schema description must survive (no str.format).
    assert "{pattern_id, por_que}" in prompt


def test_prompt_asset_carries_the_v1_contract() -> None:
    """PROMPT_VERSION and the asset must not drift apart, and the rules that
    keep the report honest have to actually be in the asset."""
    template = narrativa.load_prompt_template()
    assert narrativa.PROMPT_VERSION == "progreso_v1"
    assert "output_schema_progreso_v1.json" in template
    # The three states the report is built on, and the one that is a trap.
    for estado in ("persistente", "ausente", "no-concluyente"):
        assert estado in template
    assert "**Esto no es progreso. No lo presentes como tal.**" in template
    assert "No inventes ni recalcules números" in template
    assert "Nunca compares a través de una `frontera`" in template


def test_documented_schema_has_not_drifted_from_the_vocabulary() -> None:
    """output_schema_progreso_v1.json is documentation — structured outputs
    send the pydantic-derived schema — but the prompt names it, so a stale
    enum here is a contradictory instruction to the model."""
    doc = json.loads(
        (
            importlib.resources.files("analiza")
            / "schemas"
            / "output_schema_progreso_v1.json"
        ).read_text()
    )
    items = doc["properties"]["patrones_prioritarios"]["items"]
    assert set(items["properties"]["pattern_id"]["enum"]) == set(get_args(PatternId))
    assert doc["properties"]["patrones_prioritarios"]["maxItems"] == 3


# ── The citation guard ──────────────────────────────────────────────────────


def test_uncited_patterns_flags_a_fault_the_corpus_never_recorded() -> None:
    """The enum stops an id that does not exist; only the aggregation knows
    which ids this learner has actually produced."""
    stats = _stats()
    result = ProgresoResult.model_validate(
        {
            **VALID_PAYLOAD,
            "patrones_prioritarios": [
                {"pattern_id": "por-vs-para", "por_que": "visto"},
                {"pattern_id": "a-personal", "por_que": "inventado"},
            ],
        }
    )
    assert narrativa.uncited_patterns(result, stats) == ["a-personal"]


def test_uncited_patterns_accepts_an_empty_priority_list() -> None:
    stats = _stats()
    result = ProgresoResult.model_validate(
        {**VALID_PAYLOAD, "patrones_prioritarios": []}
    )
    assert narrativa.uncited_patterns(result, stats) == []


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_progreso_retries_an_invented_citation_then_succeeds(
    mock_cls: MagicMock,
) -> None:
    invented = {
        **VALID_PAYLOAD,
        "patrones_prioritarios": [{"pattern_id": "a-personal", "por_que": "no"}],
    }
    client = mock_cls.return_value
    client.messages.parse.side_effect = [_parsed(invented), _parsed(VALID_PAYLOAD)]

    result = narrativa.run_progreso(_stats(), CONFIG)

    assert [p.pattern_id for p in result.patrones_prioritarios] == ["por-vs-para"]
    assert client.messages.parse.call_count == 2
    retry_prompt = client.messages.parse.call_args_list[1].kwargs["messages"][0][
        "content"
    ]
    assert "a-personal" in retry_prompt


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_progreso_fails_when_the_citation_stays_invented(
    mock_cls: MagicMock,
) -> None:
    """Better no reading than one pointing at a fault the learner never made:
    the numbers are written either way."""
    invented = {
        **VALID_PAYLOAD,
        "patrones_prioritarios": [{"pattern_id": "a-personal", "por_que": "no"}],
    }
    mock_cls.return_value.messages.parse.side_effect = [
        _parsed(invented),
        _parsed(invented),
    ]
    with pytest.raises(narrativa.ExaminerError, match="a-personal"):
        narrativa.run_progreso(_stats(), CONFIG)


# ── The call shape ──────────────────────────────────────────────────────────


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_progreso_requests_structured_output(mock_cls: MagicMock) -> None:
    client = mock_cls.return_value
    client.messages.parse.return_value = _parsed(VALID_PAYLOAD)

    narrativa.run_progreso(_stats(), CONFIG)

    kwargs = client.messages.parse.call_args.kwargs
    assert kwargs["output_format"] is ProgresoResult
    assert kwargs["max_tokens"] == narrativa.MAX_TOKENS


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_progreso_retries_a_schema_violation(mock_cls: MagicMock) -> None:
    """Four priorities violates the cap. Structured outputs cannot express a
    maxItems, so pydantic catches it on parse and the retry carries the error."""
    from pydantic import ValidationError

    too_many = {
        **VALID_PAYLOAD,
        "patrones_prioritarios": [
            {"pattern_id": "por-vs-para", "por_que": str(i)} for i in range(4)
        ],
    }
    with pytest.raises(ValidationError):
        ProgresoResult.model_validate(too_many)

    client = mock_cls.return_value
    client.messages.parse.side_effect = [
        ValidationError.from_exception_data("ProgresoResult", []),
        _parsed(VALID_PAYLOAD),
    ]
    result = narrativa.run_progreso(_stats(), CONFIG)
    assert result.lectura == VALID_PAYLOAD["lectura"]
    assert client.messages.parse.call_count == 2


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("anthropic.Anthropic")
def test_run_progreso_no_text_block_fails_fast(mock_cls: MagicMock) -> None:
    """All budget spent thinking → no text block. Retrying burns another full
    budget on the same wall, so it fails with the diagnosis instead."""
    client = mock_cls.return_value
    client.messages.parse.return_value = _parsed(None, stop_reason="max_tokens")
    with pytest.raises(narrativa.ExaminerError, match="MAX_TOKENS"):
        narrativa.run_progreso(_stats(), CONFIG)
    assert client.messages.parse.call_count == 1


def test_run_progreso_without_an_api_key_fails_before_calling() -> None:
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(narrativa.ExaminerError, match="ANTHROPIC_API_KEY"):
            narrativa.run_progreso(_stats(), CONFIG)
