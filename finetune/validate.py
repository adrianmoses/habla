"""Validate generated SFT / DPO training datasets.

Usage::

    python -m finetune.validate
    python -m finetune.validate --datasets-dir finetune/datasets
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = REPO_ROOT / "finetune" / "datasets"

TOOL_CALL_RE = re.compile(r"\[TOOL_CALL:\s*(\w+)\](\{.*\})", re.DOTALL)


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"  FAIL: {path.name} line {i}: invalid JSON — {exc}")
    return records


def validate_sft(path: Path) -> int:
    """Validate SFT JSONL. Returns number of errors found."""
    print(f"Validating {path.name} ...")
    records = _load_jsonl(path)
    if not records:
        print("  FAIL: empty file")
        return 1

    errors = 0
    ids_seen: set[str] = set()
    band_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()

    for i, rec in enumerate(records):
        prefix = f"  record {i}:"

        # Required keys
        if "messages" not in rec:
            print(f"{prefix} missing 'messages'")
            errors += 1
            continue
        if "metadata" not in rec:
            print(f"{prefix} missing 'metadata'")
            errors += 1

        msgs = rec["messages"]
        meta = rec.get("metadata", {})

        # Must have system + at least 2 turns + final assistant
        if len(msgs) < 3:
            print(f"{prefix} too few messages ({len(msgs)})")
            errors += 1

        # First message must be system
        if msgs and msgs[0].get("role") != "system":
            print(f"{prefix} first message is not system role")
            errors += 1

        # Last message must be assistant with tool call
        if msgs and msgs[-1].get("role") == "assistant":
            content = msgs[-1].get("content", "")
            match = TOOL_CALL_RE.search(content)
            if not match:
                print(f"{prefix} final assistant turn missing [TOOL_CALL: ...]{{...}}")
                errors += 1
            else:
                try:
                    json.loads(match.group(2))
                except json.JSONDecodeError:
                    print(f"{prefix} tool call JSON is not parseable")
                    errors += 1
        elif msgs:
            print(f"{prefix} last message is not assistant role")
            errors += 1

        # Duplicate check via category+band+index
        rec_id = f"{meta.get('category', '')}_{meta.get('cefr_band', '')}_{i}"
        if rec_id in ids_seen:
            print(f"{prefix} duplicate id pattern")
            errors += 1
        ids_seen.add(rec_id)

        band_counts[meta.get("cefr_band", "?")] += 1
        category_counts[meta.get("category", "?")] += 1

    print(f"  {len(records)} records, {errors} errors")
    print(f"  CEFR: {dict(sorted(band_counts.items()))}")
    print(f"  Categories: {dict(sorted(category_counts.items()))}")
    return errors


def validate_dpo(path: Path) -> int:
    """Validate DPO JSONL. Returns number of errors found."""
    print(f"Validating {path.name} ...")
    records = _load_jsonl(path)
    if not records:
        print("  FAIL: empty file")
        return 1

    errors = 0
    band_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()

    for i, rec in enumerate(records):
        prefix = f"  record {i}:"

        for key in ("messages", "chosen", "rejected", "metadata"):
            if key not in rec:
                print(f"{prefix} missing '{key}'")
                errors += 1

        if "chosen" in rec and rec["chosen"].get("role") != "assistant":
            print(f"{prefix} chosen is not assistant role")
            errors += 1

        if "rejected" in rec and rec["rejected"].get("role") != "assistant":
            print(f"{prefix} rejected is not assistant role")
            errors += 1

        # Chosen must always have a tool call
        if "chosen" in rec:
            content = rec["chosen"].get("content", "")
            if not TOOL_CALL_RE.search(content):
                print(f"{prefix} chosen missing tool call")
                errors += 1

        meta = rec.get("metadata", {})
        band_counts[meta.get("cefr_band", "?")] += 1
        reason_counts[meta.get("rejection_reason", "?")] += 1

    print(f"  {len(records)} records, {errors} errors")
    print(f"  CEFR: {dict(sorted(band_counts.items()))}")
    print(f"  Rejection reasons: {dict(sorted(reason_counts.items()))}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--datasets-dir",
        type=Path,
        default=DATASETS_DIR,
        help=f"Directory containing JSONL files (default: {DATASETS_DIR})",
    )
    args = parser.parse_args()

    total_errors = 0

    sft_path = args.datasets_dir / "sft_train.jsonl"
    if sft_path.exists():
        total_errors += validate_sft(sft_path)
    else:
        print(f"Skipping SFT — {sft_path} not found")

    print()

    dpo_path = args.datasets_dir / "dpo_train.jsonl"
    if dpo_path.exists():
        total_errors += validate_dpo(dpo_path)
    else:
        print(f"Skipping DPO — {dpo_path} not found")

    print()
    if total_errors == 0:
        print("All validations passed.")
    else:
        print(f"{total_errors} total error(s) found.")

    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
