"""score_turn() and TurnResult."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from pydantic import BaseModel

from eval.fixtures.schema import CATEGORY_FILES, CEFRBand, Fixture
from eval.scoring.language import contains_english
from eval.scoring.recast import (
    error_repeated,
    recast_explicit,
    recast_present,
)
from eval.scoring.register import check_register_heuristic

# ---------------------------------------------------------------------------
# Tool-call parsing
# ---------------------------------------------------------------------------

# Two accepted tool-call surface forms in model output:
#   1) `[TOOL_CALL: name]{json}` — the original explicit format
#   2) `name({pydict_or_json})`   — the natural function-call style the base
#      Gemma model converges to (single quotes, Python-style literals)
_TOOL_CALL_HEADER_RE = re.compile(r"\[TOOL_CALL:\s*(\w+)\]\s*(?=\{)")
_FUNCTION_CALL_RE = re.compile(r"\b(\w+)\s*\(\s*(?=\{)")
_JSON_DECODER = json.JSONDecoder()


def _parse_args_payload(text: str, start: int) -> tuple[dict[str, Any], int]:
    """Parse a `{...}` payload starting at ``start``.

    Tries strict JSON first (handles nested braces via raw_decode), falls back
    to ``ast.literal_eval`` to handle Python-style dicts with single quotes
    and unquoted booleans the model emits when it follows base-model priors.
    Returns (parsed_dict, end_index). Returns ({}, start) on failure.
    """
    try:
        args, end = _JSON_DECODER.raw_decode(text, start)
        if isinstance(args, dict):
            return args, end
    except json.JSONDecodeError:
        pass
    # Fall back to Python-literal style: `{'key': 'value', ...}`.
    # Find the matching closing brace by scanning, then literal_eval that span.
    depth = 0
    in_str: str | None = None
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in "'\"":
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    args = ast.literal_eval(text[start : i + 1])
                    if isinstance(args, dict):
                        return args, i + 1
                except (ValueError, SyntaxError):
                    pass
                break
        i += 1
    return {}, start


_PYTHON_KEYWORDS = {"print", "if", "for", "while", "return", "def", "class"}


def find_tool_call_spans(text: str) -> list[tuple[int, int]]:
    """Return `(start, end)` byte offsets of every text-form tool call.

    Covers both `[TOOL_CALL: name]{...}` and `name({...})`. For the function-
    call form the span also absorbs the trailing `)` so callers that strip
    these spans don't leave a dangling paren behind.
    """
    spans: list[tuple[int, int]] = []
    for match in _TOOL_CALL_HEADER_RE.finditer(text):
        _, end = _parse_args_payload(text, match.end())
        if end > match.end():
            spans.append((match.start(), end))
    for match in _FUNCTION_CALL_RE.finditer(text):
        if match.group(1) in _PYTHON_KEYWORDS:
            continue
        if any(s <= match.start() < e for s, e in spans):
            continue
        _, end = _parse_args_payload(text, match.end())
        if end > match.end():
            # Consume the closing `)` (plus any inter-token whitespace) so the
            # sentence-counter doesn't treat the lone paren as a fragment.
            paren = end
            while paren < len(text) and text[paren] in " \t":
                paren += 1
            if paren < len(text) and text[paren] == ")":
                end = paren + 1
            spans.append((match.start(), end))
    spans.sort()
    return spans


def strip_tool_calls(text: str) -> str:
    """Remove every text-form tool call from `text`.

    Shared by the eval scorer (so `clean_response` doesn't include JSON
    payloads that poison register / L1 / sentence-count heuristics) and the
    runtime tool-handler (so tool syntax never reaches TTS).
    """
    spans = find_tool_call_spans(text)
    if not spans:
        return text.strip()
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        out.append(text[cursor:start])
        cursor = end
    out.append(text[cursor:])
    return "".join(out).strip()


def parse_tool_calls(
    response_text: str,
    api_tool_calls: list[Any] | None,
) -> list[dict[str, Any]]:
    """Extract tool calls from model output.

    Prefers structured OpenAI-style ``tool_calls`` when available, otherwise
    falls back to parsing two text formats: ``[TOOL_CALL: name]{...}`` (the
    original explicit format) and ``name({...})`` (the natural function-call
    syntax most base models converge to).
    """
    if api_tool_calls:
        parsed: list[dict[str, Any]] = []
        for tc in api_tool_calls:
            fn = tc.function if hasattr(tc, "function") else tc
            name = fn.name if hasattr(fn, "name") else fn.get("name", "")
            args_raw = (
                fn.arguments if hasattr(fn, "arguments") else fn.get("arguments", "{}")
            )
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}
            parsed.append({"name": name, "arguments": args})
        return parsed

    results: list[dict[str, Any]] = []
    for match in _TOOL_CALL_HEADER_RE.finditer(response_text):
        args, _ = _parse_args_payload(response_text, match.end())
        results.append({"name": match.group(1), "arguments": args})
    # Also pick up `name({...})` style. Skip Python keywords and common
    # false-positives that look like function calls but aren't tool emissions.
    for match in _FUNCTION_CALL_RE.finditer(response_text):
        name = match.group(1)
        if name in _PYTHON_KEYWORDS:
            continue
        # Skip if this position was already covered by the [TOOL_CALL:] match
        # above (avoids double-counting when both forms accidentally coexist).
        if any(
            r["name"] == name and isinstance(r["arguments"], dict) and r["arguments"]
            for r in results
        ):
            continue
        args, _ = _parse_args_payload(response_text, match.end())
        if args:
            results.append({"name": name, "arguments": args})
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_sentences(text: str) -> int:
    parts = [s.strip() for s in re.split(r"[.!?]+", text.strip()) if s.strip()]
    return max(len(parts), 1)


def _count_questions(text: str) -> int:
    return text.count("?")


def _extract_category(fixture_id: str) -> str:
    for cat in sorted(CATEGORY_FILES, key=len, reverse=True):
        if fixture_id.startswith(cat):
            return cat
    return "unknown"


def _extract_error_forms(fixture: Fixture) -> list[str]:
    """Collect the learner's *produced* error forms from fixture expected tool calls."""
    forms: list[str] = []
    for tc in fixture.expected.tool_calls:
        args = tc.arguments
        # Handle various key names across categories
        for key in ("errors", "errors_observed", "errors_detected"):
            errors = args.get(key, [])
            if isinstance(errors, list):
                for err in errors:
                    if isinstance(err, dict) and "produced" in err:
                        forms.append(err["produced"])
    return forms


def _extract_target_forms(fixture: Fixture) -> list[str]:
    """Collect the corrected `target` tokens from fixture expected tool calls."""
    forms: list[str] = []
    for tc in fixture.expected.tool_calls:
        args = tc.arguments
        for key in ("errors", "errors_observed", "errors_detected"):
            errors = args.get(key, [])
            if isinstance(errors, list):
                for err in errors:
                    if isinstance(err, dict) and err.get("target"):
                        forms.append(err["target"])
    return forms


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class TurnResult(BaseModel):
    """Scoring result for a single fixture."""

    fixture_id: str
    category: str
    cefr_band: CEFRBand
    model_response: str

    # Pedagogical signals (True = good, except where noted)
    recast_present: bool
    recast_explicit: bool  # True = bad (explicit correction found)
    register_correct: bool
    sentence_count_ok: bool
    question_count_ok: bool
    L1_in_response: bool  # True = bad (English detected)
    error_repeated: bool  # True = bad (hard failure)

    # Tool fidelity
    log_turn_called: bool
    tool_args_correct: bool

    # Composites
    pedagogical_score: float
    tool_fidelity_score: float
    composite_score: float


class EvalOutput(BaseModel):
    """Top-level eval output written to JSON."""

    run_id: str
    timestamp: str
    base_url: str
    fixture_count: int
    cold_start_skipped: int
    results: list[TurnResult]
    errors: list[str] = []
    aggregates: dict[str, Any]


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def score_turn(
    fixture: Fixture,
    model_response: str,
    model_tool_calls: list[Any] | None,
) -> TurnResult:
    """Score a single model response against a fixture's expected output."""
    clean_response = strip_tool_calls(model_response)
    parsed_calls = parse_tool_calls(model_response, model_tool_calls)
    error_forms = _extract_error_forms(fixture)
    target_forms = _extract_target_forms(fixture)

    # --- Pedagogical signals ---
    sig_recast_present = recast_present(
        clean_response, fixture.expected.recast_form, target_forms
    )
    sig_recast_explicit = recast_explicit(clean_response)
    sig_register = check_register_heuristic(clean_response, fixture.metadata.cefr_band)
    sig_sentence = 1 <= _count_sentences(clean_response) <= 3
    sig_question = _count_questions(clean_response) == 1
    sig_l1 = contains_english(clean_response)
    sig_error_repeated = error_repeated(clean_response, error_forms)

    # Pedagogical score: average of 6 signals (invert the "bad" ones)
    if sig_error_repeated:
        pedagogical = 0.0
    else:
        signals = [
            sig_recast_present,
            not sig_recast_explicit,
            sig_register,
            sig_sentence,
            sig_question,
            not sig_l1,
        ]
        pedagogical = sum(signals) / len(signals)

    # --- Tool fidelity ---
    sig_log_turn = any(c["name"] == "log_turn" for c in parsed_calls)

    # Check tool args: learner_utterance matches last user turn
    sig_tool_args = False
    if sig_log_turn:
        last_user_turn = ""
        for turn in reversed(fixture.conversation):
            if turn.role == "user":
                last_user_turn = turn.content
                break
        for call in parsed_calls:
            if call["name"] == "log_turn":
                args = call["arguments"]
                utterance = args.get("learner_utterance", "")
                has_errors = any(
                    args.get(k)
                    for k in ("errors", "errors_observed", "errors_detected")
                )
                if utterance == last_user_turn and has_errors:
                    sig_tool_args = True
                break

    tool_fidelity = (sig_log_turn + sig_tool_args) / 2.0

    composite = pedagogical * 0.7 + tool_fidelity * 0.3

    return TurnResult(
        fixture_id=fixture.id,
        category=_extract_category(fixture.id),
        cefr_band=fixture.metadata.cefr_band,
        model_response=model_response,
        recast_present=sig_recast_present,
        recast_explicit=sig_recast_explicit,
        register_correct=sig_register,
        sentence_count_ok=sig_sentence,
        question_count_ok=sig_question,
        L1_in_response=sig_l1,
        error_repeated=sig_error_repeated,
        log_turn_called=sig_log_turn,
        tool_args_correct=sig_tool_args,
        pedagogical_score=round(pedagogical, 4),
        tool_fidelity_score=round(tool_fidelity, 4),
        composite_score=round(composite, 4),
    )
