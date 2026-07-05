"""One-off backfill of legacy approved fixtures against the strict validator.

Two stages, each independently runnable:

1. **Local mapping** (``--apply``) — rewrite ``_approved/<cat>/*.json`` in place to:
   - Rename the log_turn errors key from ``errors_observed`` / ``errors_detected``
     to the canonical ``errors``.
   - Map non-canonical ``type`` strings (e.g. ``subjunctive_after_emotion_verb``,
     ``ser_estar_confusion``) to the canonical 10 in ``ALL_ERROR_TYPES``.
   - Lift inner field aliases to ``produced`` / ``target`` (e.g. ``example``,
     ``correct_form``, ``error_form``) using the same logic as
     ``finetune.format._normalize_error_item``.

2. **Batch payload prep** (``--build-batch <path>``) — for fixtures that still
   carry empty ``produced`` or ``target`` after stage 1, write a single Anthropic
   Message Batches request file. Submission is a separate, explicit step (the
   script never calls the API itself) — review the payload, then submit with
   the ``anthropic`` SDK or ``curl`` of your choice.

Default behaviour with no flags is a dry-run report. Pass ``--apply`` and/or
``--build-batch <path>`` to actually do work.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .prompts import ALL_ERROR_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVED_ROOT = REPO_ROOT / "eval" / "fixtures" / "_approved"

# Hard-coded mapping from non-canonical type strings observed in the legacy
# data to the canonical 10. Anything not listed is left unchanged and surfaces
# as a validator failure for manual handling.
TYPE_MAPPING: dict[str, str] = {
    # subjunctive sub-labels collapse
    "subjunctive_required": "subjunctive",
    "subjunctive_in_noun_clauses": "subjunctive",
    "subjunctive_in_concessive_clause": "subjunctive",
    "subjunctive_in_adverbial_clauses": "subjunctive",
    "subjunctive_omission": "subjunctive",
    "subjunctive_after_emotion_verb": "subjunctive",
    "subjunctive_after_esperar": "subjunctive",
    "subjunctive_after_para_que": "subjunctive",
    "subjunctive_after_conjunction": "subjunctive",
    # ser/estar variants
    "ser_estar_confusion": "ser_estar",
    "ser_estar_states": "ser_estar",
    # por/para variants
    "preposition_por_para": "por_para",
    # article / gender variants
    "article_gender": "gender_agreement",
    "adjective_agreement": "gender_agreement",
    "article_usage": "missing_article",
    "contraction_a_el": "missing_article",
    # idiom / vocabulary variants
    "anglicism": "idiomatic_error",
    "lexical_collocation": "idiomatic_error",
    # NOTE: deliberately NOT mapped (no clean canonical home — surface for
    # manual triage during backfill review):
    #   code_switch, redundant_subject_pronoun, preposition_error,
    #   conjunction_error
}

_FORBIDDEN_KEYS = ("errors_observed", "errors_detected")
_PRODUCED_ALIASES = ("produced", "error_form", "form", "example")
_TARGET_ALIASES = ("target", "correct_form", "correction")
_TYPE_ALIASES = ("type", "pattern", "error_type")


@dataclass
class Outcome:
    fixture_id: str
    category: str
    path: Path
    type_renames: list[tuple[str, str]]
    key_renames: list[str]
    field_renames: list[str]
    needs_backfill: list[dict[str, Any]]  # error dicts still missing produced/target
    unmapped_types: list[str]  # non-canonical types we couldn't map


def _coerce_error(raw: Any) -> tuple[dict[str, str], list[str], list[str]]:
    """Return (canonical_dict, field_renames_applied, unmapped_types).

    ``field_renames_applied`` lists the alias→canonical lifts done.
    ``unmapped_types`` carries the original type if it isn't in TYPE_MAPPING and
    isn't already canonical — caller decides whether to keep the entry.
    """
    if not isinstance(raw, dict):
        return {"type": "", "produced": "", "target": ""}, [], []

    field_renames: list[str] = []
    unmapped: list[str] = []

    # Lift type via aliases, then map non-canonical → canonical.
    raw_type = ""
    for k in _TYPE_ALIASES:
        if raw.get(k):
            raw_type = str(raw[k])
            if k != "type":
                field_renames.append(f"{k}→type")
            break

    canonical_type = raw_type
    if raw_type and raw_type not in ALL_ERROR_TYPES:
        if raw_type in TYPE_MAPPING:
            canonical_type = TYPE_MAPPING[raw_type]
        else:
            unmapped.append(raw_type)

    # Lift produced via aliases.
    produced = ""
    for k in _PRODUCED_ALIASES:
        if raw.get(k):
            produced = str(raw[k])
            if k != "produced":
                field_renames.append(f"{k}→produced")
            break

    # Lift target via aliases.
    target = ""
    for k in _TARGET_ALIASES:
        if raw.get(k):
            target = str(raw[k])
            if k != "target":
                field_renames.append(f"{k}→target")
            break

    return (
        {"type": canonical_type, "produced": produced, "target": target},
        field_renames,
        unmapped,
    )


def _process_fixture(data: dict[str, Any], category: str, path: Path) -> Outcome:
    """Apply local mapping to ``data`` IN PLACE; return what changed."""
    type_renames: list[tuple[str, str]] = []
    key_renames: list[str] = []
    field_renames: list[str] = []
    needs_backfill: list[dict[str, Any]] = []
    unmapped_types: list[str] = []

    for tc in data.get("expected", {}).get("tool_calls", []):
        if tc.get("name") != "log_turn":
            continue
        args = tc.get("arguments", {})

        # Lift errors_observed / errors_detected → errors.
        legacy_errors: list[Any] = []
        for k in _FORBIDDEN_KEYS:
            if k in args:
                key_renames.append(k)
                legacy_errors = args.pop(k) or []
                break
        if not args.get("errors") and legacy_errors:
            args["errors"] = legacy_errors

        # Coerce each error entry to the canonical shape.
        canonical_errors: list[dict[str, str]] = []
        for raw in args.get("errors", []) or []:
            coerced, fr, un = _coerce_error(raw)
            field_renames.extend(fr)
            unmapped_types.extend(un)
            if isinstance(raw, dict):
                old_t = raw.get("type") or raw.get("pattern") or ""
                if old_t and coerced["type"] and old_t != coerced["type"]:
                    type_renames.append((old_t, coerced["type"]))
            if not coerced["type"]:
                # Drop entries we can't even classify.
                continue
            canonical_errors.append(coerced)
            if not coerced["produced"] or not coerced["target"]:
                needs_backfill.append(
                    {
                        "fixture_id": data.get("id", path.stem),
                        "category": category,
                        "type": coerced["type"],
                        "learner_utterance": args.get("learner_utterance", ""),
                        "recast_form": data.get("expected", {}).get("recast_form")
                        or data.get("metadata", {}).get("expected_recast"),
                        "current_produced": coerced["produced"],
                        "current_target": coerced["target"],
                    }
                )
        args["errors"] = canonical_errors

    return Outcome(
        fixture_id=data.get("id", path.stem),
        category=category,
        path=path,
        type_renames=type_renames,
        key_renames=key_renames,
        field_renames=field_renames,
        needs_backfill=needs_backfill,
        unmapped_types=unmapped_types,
    )


def _walk_approved() -> list[tuple[str, Path]]:
    if not APPROVED_ROOT.exists():
        return []
    out: list[tuple[str, Path]] = []
    for cat_dir in sorted(APPROVED_ROOT.iterdir()):
        if not cat_dir.is_dir():
            continue
        for f in sorted(cat_dir.glob("*.json")):
            out.append((cat_dir.name, f))
    return out


def _build_batch_request(item: dict[str, Any], idx: int) -> dict[str, Any]:
    """One Anthropic Message Batches request to fill a missing produced/target."""
    user_prompt = (
        "You are filling missing fields on a Spanish-language-learning fixture. "
        "Given the learner's utterance and the corrected target form, identify "
        "the WRONG surface form (verbatim substring of learner_utterance) and "
        "the CORRECTED surface form. Return ONLY a JSON object: "
        '{"produced": "<verbatim wrong form>", "target": "<corrected form>"}\n\n'
        f"learner_utterance: {item['learner_utterance']!r}\n"
        f"recast_form (corrected): {item.get('recast_form')!r}\n"
        f"error type: {item['type']}\n"
        f"current produced (may be empty): {item['current_produced']!r}\n"
        f"current target (may be empty): {item['current_target']!r}\n"
    )
    return {
        "custom_id": f"backfill__{item['category']}__{item['fixture_id']}__{idx:03d}",
        "params": {
            "model": "claude-opus-4-5",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": user_prompt}],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite _approved/ files in place with local mappings (stage 1).",
    )
    parser.add_argument(
        "--build-batch",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write Anthropic batch request payload to PATH (stage 2). "
        "Implies the local mapping has been applied (or is being applied via "
        "--apply in the same run).",
    )
    args = parser.parse_args()

    items = _walk_approved()
    if not items:
        print(f"no fixtures under {APPROVED_ROOT}", file=sys.stderr)
        return 1

    outcomes: list[Outcome] = []
    type_rename_counter: Counter[tuple[str, str]] = Counter()
    key_rename_counter: Counter[str] = Counter()
    unmapped_counter: Counter[str] = Counter()
    backfill_items: list[dict[str, Any]] = []

    for category, path in items:
        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            print(f"  ! parse error {path}: {exc}", file=sys.stderr)
            continue

        outcome = _process_fixture(data, category, path)
        outcomes.append(outcome)

        for old, new in outcome.type_renames:
            type_rename_counter[(old, new)] += 1
        for k in outcome.key_renames:
            key_rename_counter[k] += 1
        for t in outcome.unmapped_types:
            unmapped_counter[t] += 1
        backfill_items.extend(outcome.needs_backfill)

        if args.apply and (
            outcome.type_renames or outcome.key_renames or outcome.field_renames
        ):
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ---- Report ----
    print(f"scanned {len(outcomes)} fixtures")
    print()
    print("== forbidden key renames (errors_observed / errors_detected → errors) ==")
    for k, n in key_rename_counter.most_common():
        print(f"  {k}: {n}")
    print()
    print("== type renames (legacy → canonical) ==")
    for (old, new), n in type_rename_counter.most_common():
        print(f"  {old} → {new}: {n}")
    print()
    print("== unmapped non-canonical types (need manual triage) ==")
    for t, n in unmapped_counter.most_common():
        print(f"  {t}: {n}")
    print()
    print(
        f"== entries still missing produced/target after mapping: "
        f"{len(backfill_items)} =="
    )

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\nlocal mapping stage: {mode}")

    if args.build_batch:
        payload = [_build_batch_request(it, i) for i, it in enumerate(backfill_items)]
        args.build_batch.parent.mkdir(parents=True, exist_ok=True)
        args.build_batch.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\nwrote {len(payload)} batch requests → {args.build_batch}")
        print(
            "submit with the anthropic SDK separately; "
            "this script does NOT call the API."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
