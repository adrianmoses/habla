"""Validate fixtures against spec rules before they enter the review queue.

Pure functions — no I/O in core. CLI mode at the bottom walks a directory of
pending fixtures and prints a pass/fail report per category.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from eval.fixtures.schema import ColdStartFixture, Fixture, parse_fixture

from .prompts import ALL_ERROR_TYPES

_ALL_ERROR_TYPES_SET = set(ALL_ERROR_TYPES)
_FORBIDDEN_ERROR_KEYS = ("errors_observed", "errors_detected")


def _produced_form_leaks(produced: str, response: str) -> bool:
    """Check whether the learner's wrong form appears verbatim in the response.

    Uses Unicode-aware word boundaries (\\b) to avoid false positives where
    `produced` is a substring of a longer Spanish word — e.g., produced="es"
    must not match inside "está", "estás", "estamos". Word boundaries also
    work for multi-word produced forms ("es cerca", "el casa rojo") because
    the boundary is anchored at the outer ends of the phrase.
    """
    pattern = r"\b" + re.escape(produced) + r"\b"
    return re.search(pattern, response, re.IGNORECASE | re.UNICODE) is not None


EXPLICIT_CORRECTION_PATTERNS = [
    r"pero\s+es\b",
    r"se\s+dice\b",
    r"la\s+forma\s+correcta",
    r"lo\s+correcto\s+es",
    r"deber[íi]as?\s+decir",
    r"no\s+se\s+dice",
    r"should\s+be\b",
    r"actually\b",
    r"dijiste\s+['\"\w]+\s+pero\b",
]
_EXPLICIT_RE = re.compile("|".join(EXPLICIT_CORRECTION_PATTERNS), re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"[.!?]+")


@dataclass
class ValidationResult:
    fixture_id: str
    category: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _sentence_count(text: str) -> int:
    return len([s for s in _SENTENCE_SPLIT.split(text) if s.strip()])


def _is_english(text: str) -> bool:
    from langdetect import LangDetectException, detect

    try:
        return detect(text) == "en"
    except LangDetectException:
        return False


def _log_turn(fixture: Fixture) -> dict | None:
    for tc in fixture.expected.tool_calls:
        if tc.name == "log_turn":
            return tc.arguments
    return None


def universal_checks(fixture: Fixture) -> list[str]:
    """Spec §'Validation before review' — universal checks."""
    errs: list[str] = []
    response = fixture.expected.response_text

    sc = _sentence_count(response)
    if not 1 <= sc <= 3:
        errs.append(f"sentence_count={sc} (must be 1–3)")

    if response.count("?") != 1:
        errs.append(f"question_count={response.count('?')} (must be exactly 1)")

    if _EXPLICIT_RE.search(response):
        errs.append("explicit_correction phrase found in response_text")

    if "muy bien" in response.lower():
        errs.append("'muy bien' appears in response_text (banned)")

    log_turn = _log_turn(fixture)
    if log_turn is None:
        errs.append("log_turn not present in expected.tool_calls")

    if log_turn:
        for forbidden in _FORBIDDEN_ERROR_KEYS:
            if forbidden in log_turn:
                errs.append(
                    f"log_turn uses non-canonical key '{forbidden}'; "
                    "use 'errors' instead"
                )

    if fixture.metadata.errors_present:
        recast = fixture.metadata.expected_recast or fixture.expected.recast_form
        if not recast:
            errs.append("errors_present set but no expected_recast/recast_form")
        elif recast not in response:
            errs.append(f"expected_recast '{recast}' not in response_text")

        if log_turn and isinstance(log_turn.get("errors"), list):
            for idx, err in enumerate(log_turn["errors"]):
                if not isinstance(err, dict):
                    errs.append(f"errors[{idx}] is not an object")
                    continue
                err_type = err.get("type", "")
                produced = err.get("produced", "")
                target = err.get("target", "")
                if err_type not in _ALL_ERROR_TYPES_SET:
                    errs.append(
                        f"errors[{idx}].type='{err_type}' is not a canonical "
                        f"type (must be one of {sorted(_ALL_ERROR_TYPES_SET)})"
                    )
                if not produced:
                    errs.append(f"errors[{idx}].produced is empty")
                if not target:
                    errs.append(f"errors[{idx}].target is empty")
                if produced and _produced_form_leaks(produced, response):
                    errs.append(f"error form '{produced}' appears in response_text")

    if _is_english(response) and not fixture.metadata.L1_used:
        errs.append("response_text detected as English")

    return errs


def _check_multi_error(fixture: Fixture) -> list[str]:
    errs: list[str] = []
    if fixture.metadata.difficulty != "multi_error":
        errs.append("difficulty must be 'multi_error'")
    if not fixture.expected.priority_error:
        errs.append("expected.priority_error required for multi_error")
    log_turn = _log_turn(fixture) or {}
    observed = {e.get("type") for e in log_turn.get("errors", [])}
    missing = set(fixture.metadata.errors_present) - observed
    if missing:
        errs.append(f"log_turn.errors missing types: {sorted(missing)}")
    return errs


def _check_l1_handling(fixture: Fixture) -> list[str]:
    errs: list[str] = []
    if not fixture.metadata.L1_used:
        errs.append("metadata.L1_used must be true")
    log_turn = _log_turn(fixture) or {}
    if not log_turn.get("L1_used"):
        errs.append("log_turn.L1_used must be true")
    if _is_english(fixture.expected.response_text):
        errs.append("response_text detected as English")
    return errs


def _check_mimicry_cycle(fixture: Fixture) -> list[str]:
    errs: list[str] = []
    response = fixture.expected.response_text
    word_count = len(response.split())
    if word_count > 20:
        errs.append(f"response_text has {word_count} words (max 20)")
    if "muy bien" in response.lower():
        errs.append("'muy bien' banned in mimicry_cycle")
    tags = set(fixture.metadata.tags)
    stages = {"offer", "repeat", "extend"}
    if not tags & stages:
        errs.append("must tag with one of offer/repeat/extend")
    if "offer" in tags:
        invites = ["repetir", "repite", "di conmigo", "repeat"]
        if not any(inv in response.lower() for inv in invites):
            errs.append("offer stage must contain a repetition invitation")
    return errs


def _check_cold_start(fixture: ColdStartFixture) -> list[str]:
    errs: list[str] = []
    if len(fixture.learner_turns) != 4:
        errs.append("cold_start must have exactly 4 learner_turns")
    pl = fixture.expected_profile_update.production_level
    if not (pl.min <= fixture.true_level <= pl.max):
        errs.append(
            f"true_level {fixture.true_level} outside expected range "
            f"[{pl.min}, {pl.max}]"
        )
    if not fixture.expected_profile_update.is_calibrated:
        errs.append("is_calibrated must be true after 4 turns")
    return errs


def _check_tool_call_correctness(fixture: Fixture) -> list[str]:
    errs: list[str] = []
    log_turn = _log_turn(fixture) or {}
    last_user = next(
        (t.content for t in reversed(fixture.conversation) if t.role == "user"),
        None,
    )
    logged = log_turn.get("learner_utterance")
    if logged != last_user:
        errs.append("log_turn.learner_utterance does not exact-match last user turn")
    return errs


def _check_error_pattern_threshold(fixture: Fixture) -> list[str]:
    errs: list[str] = []
    if len(fixture.conversation) < 4:
        errs.append(f"conversation must have ≥4 turns, got {len(fixture.conversation)}")
    tags = set(fixture.metadata.tags)
    tool_names = {tc.name for tc in fixture.expected.tool_calls}
    expect_log_error = bool(
        tags & {"third_occurrence", "different_contexts", "declining_severity"}
    )
    if expect_log_error and "log_error" not in tool_names:
        errs.append("scenario requires log_error tool call")
    if "second_occurrence" in tags and "log_error" in tool_names:
        errs.append("second_occurrence must NOT call log_error")
    return errs


_CATEGORY_DISPATCH = {
    "multi_error": _check_multi_error,
    "l1_handling": _check_l1_handling,
    "mimicry_cycle": _check_mimicry_cycle,
    "tool_call_correctness": _check_tool_call_correctness,
    "error_pattern_threshold": _check_error_pattern_threshold,
}


def validate_one(
    fixture: Fixture | ColdStartFixture, category: str
) -> ValidationResult:
    result = ValidationResult(fixture_id=fixture.id, category=category)
    if category == "cold_start":
        if not isinstance(fixture, ColdStartFixture):
            result.errors.append("cold_start fixture must be ColdStartFixture type")
            return result
        result.errors.extend(_check_cold_start(fixture))
        return result

    if not isinstance(fixture, Fixture):
        result.errors.append(f"category {category} requires standard Fixture type")
        return result

    result.errors.extend(universal_checks(fixture))
    check = _CATEGORY_DISPATCH.get(category)
    if check:
        result.errors.extend(check(fixture))
    return result


def _iter_pending(root: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    if not root.exists():
        return out
    for category_dir in sorted(root.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        for f in sorted(category_dir.glob("*.json")):
            if f.name.startswith("_run_") or f.name.startswith("_"):
                continue
            out.append((category, f))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", type=Path, help="directory holding per-category subdirs"
    )
    parser.add_argument("--report", action="store_true", help="print summary table")
    args = parser.parse_args()

    results: list[ValidationResult] = []
    for category, file in _iter_pending(args.path):
        try:
            data = json.loads(file.read_text())
            fixture = parse_fixture(data)
        except Exception as exc:
            r = ValidationResult(fixture_id=file.stem, category=category)
            r.errors.append(f"parse error: {exc}")
            results.append(r)
            continue
        results.append(validate_one(fixture, category))

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"{passed}/{total} fixtures passed validation")
    if args.report:
        by_cat: dict[str, tuple[int, int]] = {}
        for r in results:
            p, t = by_cat.get(r.category, (0, 0))
            by_cat[r.category] = (p + int(r.ok), t + 1)
        print()
        for cat, (p, t) in sorted(by_cat.items()):
            print(f"  {cat:28s} {p}/{t}")
        print()
        for r in results:
            if not r.ok:
                print(f"FAIL {r.category}/{r.fixture_id}:")
                for e in r.errors:
                    print(f"  - {e}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
