"""Consolidate _approved/<category>/*.json into final category JSON files."""

from __future__ import annotations

import argparse
import json
import types
from pathlib import Path
from typing import get_args, get_origin

from pydantic import BaseModel

from eval.fixtures.schema import (
    CATEGORY_FILES,
    ColdStartFixture,
    Fixture,
    load_fixtures,
    parse_fixture,
)

from .prompts import TARGET_COUNTS

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"
APPROVED_ROOT = FIXTURES_ROOT / "_approved"


def _strip_to_model(data: object, model_cls: type[BaseModel]) -> object:
    """Recursively drop keys not declared in *model_cls*."""
    if not isinstance(data, dict):
        return data
    result: dict = {}
    for name, field in model_cls.model_fields.items():
        if name not in data:
            continue
        value = data[name]
        ann = field.annotation
        # Unwrap Optional (Union[X, None])
        if isinstance(ann, types.UnionType):
            args = [a for a in get_args(ann) if a is not type(None)]
            if len(args) == 1:
                ann = args[0]
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            result[name] = _strip_to_model(value, ann)
        elif get_origin(ann) is list and isinstance(value, list):
            inner = get_args(ann)
            if inner and isinstance(inner[0], type) and issubclass(inner[0], BaseModel):
                result[name] = [_strip_to_model(item, inner[0]) for item in value]
            else:
                result[name] = value
        else:
            result[name] = value
    return result


def _collect(category: str) -> list[dict]:
    cat_dir = APPROVED_ROOT / category
    if not cat_dir.exists():
        return []
    out: list[dict] = []
    for f in sorted(cat_dir.glob("*.json")):
        data = json.loads(f.read_text())
        model_cls = (
            ColdStartFixture if data.get("type") == "cold_start_sequence" else Fixture
        )
        stripped = _strip_to_model(data, model_cls)
        assert isinstance(stripped, dict)
        parse_fixture(stripped)  # validates
        out.append(stripped)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail if any category is below its target count",
    )
    args = parser.parse_args()

    rows: list[tuple[str, int, int, str]] = []
    short = False

    for category in CATEGORY_FILES:
        fixtures = _collect(category)
        fixtures.sort(key=lambda f: f["id"])
        target = sum(TARGET_COUNTS.get(category, {}).values())
        status = "ok"
        if len(fixtures) < target:
            status = "short"
            short = True
        elif len(fixtures) > target:
            # Over target is fine — it's bonus data, not a problem. The
            # prompt-engineered categories (l1_handling, register_boundary, ...)
            # intentionally have small TARGET_COUNTS and will stay above them.
            status = "over (ok)"
        rows.append((category, len(fixtures), target, status))

        out_file = FIXTURES_ROOT / f"{category}.json"
        out_file.write_text(json.dumps(fixtures, indent=2, ensure_ascii=False))

    print(f"{'category':28s} {'count':>6s} {'target':>7s}  status")
    for cat, count, target, status in rows:
        print(f"{cat:28s} {count:6d} {target:7d}  {status}")

    loaded = load_fixtures(FIXTURES_ROOT)
    print(f"\nload_fixtures() validated {len(loaded)} fixtures across all files")

    if short and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
