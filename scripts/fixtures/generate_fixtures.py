"""Generate fixtures via the Anthropic Message Batches API.

One batch per (category) submits all band requests together, using prompt
caching on the shared system prefix. Results land in
``eval/fixtures/_pending/<category>/<id>.json`` after validation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from eval.fixtures.schema import CEFRBand, parse_fixture

from .prompts import CATEGORIES, TARGET_COUNTS
from .prompts.base import SYSTEM_PREFIX
from .validate_fixtures import validate_one

MODEL = "claude-opus-4-5"
MAX_TOKENS = 4096
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"
PENDING_ROOT = FIXTURES_ROOT / "_pending"
APPROVED_ROOT = FIXTURES_ROOT / "_approved"
REJECTED_ROOT = FIXTURES_ROOT / "_rejected"


@dataclass
class BatchRequest:
    custom_id: str
    category: str
    band: CEFRBand
    user_prompt: str


def _build_requests(
    categories: list[str],
    bands: list[CEFRBand] | None,
    multiplier: float,
    max_per_cell: int | None = None,
) -> list[BatchRequest]:
    requests: list[BatchRequest] = []
    for cat in categories:
        builder = CATEGORIES[cat]
        targets = TARGET_COUNTS[cat]
        for band, target in targets.items():
            if bands and band not in bands:
                continue
            n = max(1, math.ceil(target * multiplier))
            existing = _count_existing(cat, band)
            remaining = max(0, n - existing)
            if max_per_cell is not None:
                remaining = min(remaining, max_per_cell)
            if remaining == 0:
                continue
            for i, prompt in enumerate(builder(remaining, band)):
                requests.append(
                    BatchRequest(
                        custom_id=f"{cat}__{band}__{existing + i:03d}",
                        category=cat,
                        band=band,
                        user_prompt=prompt,
                    )
                )
    return requests


def _count_existing(category: str, band: CEFRBand) -> int:
    """Count fixtures already named ``{category}_{band}_*`` across every staging dir.

    This drives the seq number for newly generated fixtures. Counting only
    `_pending/` (the historical bug) made fresh runs restart at seq 001 and
    silently overwrite same-named fixtures already moved to `_approved/` or
    `_rejected/` via shutil.move. Sum across all three so seq numbers always
    advance.
    """
    pattern = re.compile(rf"^{re.escape(category)}_{band}_")
    total = 0
    for root in (PENDING_ROOT, APPROVED_ROOT, REJECTED_ROOT):
        cat_dir = root / category
        if not cat_dir.exists():
            continue
        total += sum(1 for f in cat_dir.glob("*.json") if pattern.match(f.name))
    return total


def _request_payload(req: BatchRequest) -> dict[str, Any]:
    return {
        "custom_id": req.custom_id,
        "params": {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": [
                {
                    "type": "text",
                    "text": SYSTEM_PREFIX,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [
                {"role": "user", "content": req.user_prompt},
            ],
        },
    }


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[start : end + 1])


def _slug(prompt: str) -> str:
    m = re.search(r"domain:\s*\*\*([\w_]+)", prompt) or re.search(
        r"(?:Scenario|Trap|Stage|scenario):\s*\*\*([\w_]+)", prompt
    )
    return (m.group(1).lower() if m else "gen")[:24]


def _write_fixture(
    category: str,
    band: CEFRBand,
    data: dict[str, Any],
    slug: str,
    seq: int,
) -> Path:
    cat_dir = PENDING_ROOT / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    fixture_id = f"{category}_{band}_{slug}_{seq:03d}"
    data["id"] = fixture_id
    out = cat_dir / f"{fixture_id}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return out


def _submit_and_collect(
    client: Any, requests: list[BatchRequest], poll_seconds: int
) -> Iterable[tuple[BatchRequest, dict[str, Any] | str]]:
    by_cat: dict[str, list[BatchRequest]] = {}
    for r in requests:
        by_cat.setdefault(r.category, []).append(r)

    for category, reqs in by_cat.items():
        print(f"[{category}] submitting batch of {len(reqs)} requests")
        batch = client.messages.batches.create(
            requests=[_request_payload(r) for r in reqs]
        )
        print(f"[{category}] batch_id={batch.id}")

        while True:
            batch = client.messages.batches.retrieve(batch.id)
            counts = batch.processing_status
            print(f"[{category}] status={counts}")
            if counts == "ended":
                break
            time.sleep(poll_seconds)

        by_id = {r.custom_id: r for r in reqs}
        for result in client.messages.batches.results(batch.id):
            req = by_id.get(result.custom_id)
            if req is None:
                continue
            r_type = result.result.type
            if r_type != "succeeded":
                yield req, f"{r_type}: {result.result}"
                continue
            message = result.result.message
            text = "".join(
                block.text for block in message.content if block.type == "text"
            )
            yield req, text


def _process_results(
    results: Iterable[tuple[BatchRequest, dict[str, Any] | str]],
) -> tuple[int, int]:
    manifest: dict[str, list[dict[str, Any]]] = {}
    accepted = rejected = 0
    seq_counters: dict[tuple[str, CEFRBand], int] = {}

    for req, payload in results:
        key = (req.category, req.band)
        seq_counters[key] = seq_counters.get(key, _count_existing(*key))
        entry: dict[str, Any] = {"custom_id": req.custom_id}

        if isinstance(payload, dict):
            data = payload
            text = None
        else:
            text = str(payload)

        if text is not None:
            try:
                data = _extract_json(text)
            except Exception as exc:
                entry["status"] = "parse_error"
                entry["detail"] = str(exc)
                manifest.setdefault(req.category, []).append(entry)
                rejected += 1
                print(f"  ✗ {req.custom_id}: parse error {exc}")
                continue

        seq_counters[key] += 1
        seq = seq_counters[key]
        fixture_path: Path | None = None
        try:
            fixture_path = _write_fixture(
                req.category, req.band, data, _slug(req.user_prompt), seq
            )
            fixture = parse_fixture(json.loads(fixture_path.read_text()))
            validation = validate_one(fixture, req.category)
        except Exception as exc:
            entry["status"] = "schema_error"
            entry["detail"] = str(exc)[:500]
            manifest.setdefault(req.category, []).append(entry)
            rejected += 1
            # Clean up the broken file and reclaim the seq number so the next
            # attempt reuses it. Without this, the file leaks into _pending/
            # and gets rejected a second time by auto-approve, double-counting.
            if fixture_path is not None and fixture_path.exists():
                fixture_path.unlink()
            seq_counters[key] -= 1
            print(f"  ✗ {req.custom_id}: schema error {exc}")
            continue

        entry["status"] = "ok" if validation.ok else "validation_error"
        entry["fixture_id"] = fixture.id
        if not validation.ok:
            entry["errors"] = validation.errors
            fixture_path.unlink()
            seq_counters[key] -= 1
            rejected += 1
            print(f"  ✗ {fixture.id}: {'; '.join(validation.errors)}")
        else:
            accepted += 1
            print(f"  ✓ {fixture.id}")
        manifest.setdefault(req.category, []).append(entry)

    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    for cat, entries in manifest.items():
        run_file = PENDING_ROOT / cat / f"_run_{ts}.json"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        run_file.write_text(json.dumps(entries, indent=2))
    return accepted, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--categories",
        nargs="+",
        default=list(CATEGORIES.keys()),
        choices=list(CATEGORIES.keys()),
    )
    parser.add_argument(
        "--bands",
        nargs="+",
        default=None,
        choices=["A1", "A2", "B1", "B2", "C1"],
    )
    parser.add_argument(
        "--count-multiplier",
        type=float,
        default=1.2,
        help="oversample ratio vs target counts (default 1.2)",
    )
    parser.add_argument(
        "--max-per-cell",
        type=int,
        default=None,
        metavar="N",
        help="cap new fixtures per (category, band) cell at N. Use for cheap "
        "pre-flight runs (e.g. --max-per-cell 3 generates ≤3 per cell, ~$1-2 "
        "across the full target categories) before committing to scale.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()

    load_dotenv()

    requests = _build_requests(
        args.categories, args.bands, args.count_multiplier, args.max_per_cell
    )
    print(f"Planned {len(requests)} generation requests")
    if args.max_per_cell is not None:
        print(f"  (capped to ≤{args.max_per_cell} per (category, band) cell)")
    if not requests:
        return 0

    if args.dry_run:
        for r in requests[:3]:
            payload = _request_payload(r)
            print(f"\n--- {r.custom_id} ({r.category} / {r.band}) ---")
            print(payload["params"]["messages"][0]["content"][:400])
        print(f"\n(printed 3 of {len(requests)} requests)")
        return 0

    try:
        from anthropic import Anthropic
    except ImportError:
        print("anthropic SDK not installed; run `uv sync --extra eval`")
        return 2

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set")
        return 2

    client = Anthropic()
    results = _submit_and_collect(client, requests, args.poll_seconds)
    accepted, rejected = _process_results(results)
    print(f"\nAccepted: {accepted}  Rejected: {rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
