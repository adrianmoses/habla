"""Generate the SFT training dataset from consolidated eval fixtures.

Usage::

    python -m finetune.generate                  # consolidate + write SFT
    python -m finetune.generate --no-consolidate # skip consolidation step
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from eval.fixtures.schema import Fixture, load_fixtures
from finetune.format import _extract_category, fixture_to_sft

# Only these three categories exercise the two failing eval metrics
# (recast_present, tool_args_correct). The others live under prompt
# engineering — including them here trains the model on behaviors that
# already pass and dilutes the signal on what we actually want to fix.
FINETUNE_CATEGORIES: set[str] = {
    "single_error_recast",
    "multi_error",
    "tool_call_correctness",
}

_TOOL_CALL_RE = re.compile(r"\[TOOL_CALL: log_turn\]\s*(\{.*)", re.DOTALL)


def _has_empty_error_field(rec: dict) -> bool:
    """Return True if the SFT record's log_turn.errors has any entry with an
    empty produced or target field. These records teach the wrong pattern for
    tool_args_correct and should be filtered in --strict mode."""
    asst = rec["messages"][-1]
    m = _TOOL_CALL_RE.search(asst["content"])
    if not m:
        return False
    try:
        args, _ = json.JSONDecoder().raw_decode(m.group(1))
    except json.JSONDecodeError:
        return False
    errors = args.get("errors", [])
    if not errors:
        return False
    return any(
        not e.get("produced") or not e.get("target")
        for e in errors
        if isinstance(e, dict)
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"
DATASETS_DIR = REPO_ROOT / "finetune" / "datasets"


def _consolidate() -> int:
    """Run the fixture consolidation pipeline."""
    print("Running fixture consolidation ...")
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate_eval_fixtures.py"),
            "consolidate",
        ],
        cwd=str(REPO_ROOT),
    )
    print(result.returncode)
    return result.returncode


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-consolidate",
        action="store_true",
        help="Skip fixture consolidation (assumes already done)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATASETS_DIR,
        help=f"Output directory (default: {DATASETS_DIR})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Skip fixtures whose log_turn.errors contain any entry with empty "
        "produced/target. These are legacy-data residuals that would teach "
        "the wrong pattern for tool_args_correct.",
    )
    parser.add_argument(
        "--include-all-categories",
        action="store_true",
        help="Include every fixture category, not just the fine-tune targets "
        "(single_error_recast, multi_error, tool_call_correctness). Use only "
        "if you explicitly want non-training-relevant categories in the SFT "
        "pool — by default they're filtered out.",
    )
    args = parser.parse_args()

    # Step 1: consolidate
    if not args.no_consolidate:
        rc = _consolidate()
        if rc != 0:
            print("Consolidation failed — aborting.", file=sys.stderr)
            return 1
        print()

    # Step 2: load fixtures
    fixtures = load_fixtures(FIXTURES_ROOT)
    standard = [f for f in fixtures if isinstance(f, Fixture)]
    cold_skipped = len(fixtures) - len(standard)

    if args.include_all_categories:
        eligible = standard
        cat_skipped = 0
    else:
        eligible = [
            f for f in standard if _extract_category(f.id) in FINETUNE_CATEGORIES
        ]
        cat_skipped = len(standard) - len(eligible)

    print(
        f"Loaded {len(fixtures)} fixtures "
        f"({len(standard)} standard, {cold_skipped} cold_start skipped, "
        f"{cat_skipped} non-finetune-category skipped)"
    )

    if not eligible:
        print("No eligible fixtures to convert.", file=sys.stderr)
        return 1

    # Step 3: convert
    sft_records: list[dict] = []
    dropped_strict = 0
    for f in eligible:
        rec = fixture_to_sft(f)
        if args.strict and _has_empty_error_field(rec):
            dropped_strict += 1
            continue
        sft_records.append(rec)
    band_counts: Counter[str] = Counter(f.metadata.cefr_band for f in eligible)
    cat_counts: Counter[str] = Counter(_extract_category(f.id) for f in eligible)

    # Step 4: write
    sft_path = args.output_dir / "sft_train.jsonl"
    _write_jsonl(sft_path, sft_records)
    print(f"Wrote {len(sft_records)} SFT examples → {sft_path}")
    if args.strict:
        print(
            f"  (strict mode: dropped {dropped_strict} records with empty produced/target)"
        )
    print("\nCategory distribution:")
    for cat, n in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:28s} {n}")

    print("\nCEFR distribution:")
    for band in ["A1", "A2", "B1", "B2", "C1"]:
        print(f"  {band}: {band_counts.get(band, 0)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
