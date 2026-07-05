"""Replay cold_start fixtures through the live llama.cpp endpoint.

Spec 049 §6. For each fixture in ``eval/fixtures/cold_start.json``:

1. Render the cold-start system prompt via the runtime's
   ``render_system_prompt`` + ``COLD_START_INSTRUCTIONS`` (so the model
   sees exactly what it sees in production).
2. Replay the four learner utterances as ``user`` messages, asking
   ``/v1/chat/completions`` with ``tools=HABLE_YA_TOOLS`` after each.
3. Parse the model's emitted ``log_turn`` call. Extract ``cefr_band``.
4. Apply :func:`place_band` to the four per-turn bands.
5. Compare to the fixture's ``true_band`` (per session) and per-turn
   ``band_indicators``.

Reports:

* Per-fixture rows.
* Per-band aggregates: accuracy + MAE.
* Overall accuracy + MAE + 5x5 confusion matrix.
* ``band_missing`` count (model omitted or emitted out-of-enum).

Exits non-zero if ``overall_accuracy < ACCURACY_BAR`` or
``overall_mae > MAE_BAR``. CI runs this with ``continue-on-error: true``
in this slice's landing PR; promotion to a blocking gate is decided
pre-merge once the local replay is reviewed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openai
from rich.console import Console
from rich.table import Table

from eval.agent.run_agent_eval import LLAMA_MODEL_ID
from eval.fixtures.schema import CEFRBand, ColdStartFixture, parse_fixture
from eval.scoring.turn import parse_tool_calls
from hable_ya.config import settings
from hable_ya.learner.bands import (
    ALL_BANDS,
    BAND_MIDPOINT,
    is_valid_cefr_band,
)
from hable_ya.learner.leveling.policy import PlacementDecision, place_band
from hable_ya.pipeline.prompts.builder import render_cold_start_prompt
from hable_ya.tools.schema import HABLE_YA_TOOLS

console = Console()

ACCURACY_BAR = 0.75
MAE_BAR = 0.20
DEFAULT_FIXTURES = Path("eval/fixtures/cold_start.json")
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_MAX_TOKENS = 1024


@dataclass
class FixtureResult:
    fixture_id: str
    true_band: CEFRBand
    predicted_band: CEFRBand | None
    per_turn_bands: list[CEFRBand | None]
    band_indicators_per_turn: list[list[CEFRBand]]
    band_missing: int = 0
    placement_signals: dict[str, Any] = field(default_factory=dict)


async def _call_agent(
    client: openai.AsyncOpenAI,
    *,
    system_prompt: str,
    transcript: list[dict[str, str]],
    timeout: float,
    max_tokens: int,
    no_thinking: bool,
) -> tuple[str, list[Any] | None]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]
    messages.extend(transcript)

    extra_body: dict[str, Any] = {"tools": HABLE_YA_TOOLS}
    if no_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=LLAMA_MODEL_ID,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.0,
            max_tokens=max_tokens,
            extra_body=extra_body,
        ),
        timeout=timeout,
    )
    choice = response.choices[0]
    text = choice.message.content or ""
    return text, choice.message.tool_calls


def _extract_cefr_band(
    text: str, api_tool_calls: list[Any] | None
) -> CEFRBand | None:
    """Find the ``log_turn`` call and return its ``cefr_band`` if valid."""
    for call in parse_tool_calls(text, api_tool_calls=api_tool_calls):
        if call.get("name") != "log_turn":
            continue
        args = call.get("arguments")
        if not isinstance(args, dict):
            continue
        raw = args.get("cefr_band")
        if is_valid_cefr_band(raw):
            return raw
    return None


async def replay_fixture(
    fixture: ColdStartFixture,
    client: openai.AsyncOpenAI,
    *,
    timeout: float,
    max_tokens: int,
    no_thinking: bool,
    verbose: bool,
) -> FixtureResult:
    """Replay one fixture's four learner turns; return the placement result."""
    # Match the runtime: on a fresh DB the bootstrap band is
    # ``default_learner_band``, not the persona's true band. The cold-start
    # ladder is band-agnostic; the register guidance reads at the bootstrap.
    bootstrap_band: CEFRBand = settings.default_learner_band  # type: ignore[assignment]
    system_prompt = render_cold_start_prompt(bootstrap_band)
    transcript: list[dict[str, str]] = []
    per_turn_bands: list[CEFRBand | None] = []
    band_missing = 0

    for turn in fixture.learner_turns:
        transcript.append({"role": "user", "content": turn.utterance})
        text, api_tool_calls = await _call_agent(
            client,
            system_prompt=system_prompt,
            transcript=transcript,
            timeout=timeout,
            max_tokens=max_tokens,
            no_thinking=no_thinking,
        )
        emitted = _extract_cefr_band(text, api_tool_calls)
        if emitted is None:
            band_missing += 1
            if verbose:
                console.log(
                    f"[yellow]{fixture.id}[/yellow] turn "
                    f"{len(per_turn_bands) + 1}: missing cefr_band"
                )
        per_turn_bands.append(emitted)
        transcript.append({"role": "assistant", "content": text})

    decision = place_band(
        per_turn_bands,
        floor_band=settings.default_learner_band,  # type: ignore[arg-type]
        min_valid_turns=settings.placement_min_valid_turns,
    )

    return FixtureResult(
        fixture_id=fixture.id,
        true_band=fixture.true_band,
        predicted_band=decision.band if decision is not None else None,
        per_turn_bands=per_turn_bands,
        band_indicators_per_turn=[
            list(t.signals.band_indicators) for t in fixture.learner_turns
        ],
        band_missing=band_missing,
        placement_signals=(
            dict(decision.signals)
            if isinstance(decision, PlacementDecision)
            else {}
        ),
    )


def _print_per_fixture_table(results: list[FixtureResult]) -> None:
    table = Table(title="Per-fixture results")
    table.add_column("fixture")
    table.add_column("true")
    table.add_column("pred")
    table.add_column("per-turn emitted")
    table.add_column("per-turn indicators")
    table.add_column("missing")
    for r in results:
        emitted = ",".join(b or "-" for b in r.per_turn_bands)
        indicators = " | ".join(
            "/".join(ind) for ind in r.band_indicators_per_turn
        )
        pred_label = r.predicted_band or "(abstain)"
        agree = r.predicted_band == r.true_band
        marker = "[green]✓[/green]" if agree else "[red]✗[/red]"
        table.add_row(
            r.fixture_id,
            r.true_band,
            f"{pred_label} {marker}",
            emitted,
            indicators,
            str(r.band_missing),
        )
    console.print(table)


def _print_per_band_aggregate(results: list[FixtureResult]) -> None:
    by_band: dict[CEFRBand, list[FixtureResult]] = {b: [] for b in ALL_BANDS}
    for r in results:
        by_band[r.true_band].append(r)
    table = Table(title="Per-band aggregates")
    table.add_column("true_band")
    table.add_column("n")
    table.add_column("accuracy")
    table.add_column("MAE")
    for band in ALL_BANDS:
        bucket = by_band[band]
        if not bucket:
            continue
        n = len(bucket)
        correct = sum(1 for r in bucket if r.predicted_band == band)
        mae_band = (
            sum(
                (
                    abs(
                        BAND_MIDPOINT[r.predicted_band]
                        - BAND_MIDPOINT[r.true_band]
                    )
                    if r.predicted_band is not None
                    else 1.0  # full bucket-width penalty for abstain
                )
                for r in bucket
            )
            / n
        )
        table.add_row(
            band,
            str(n),
            f"{correct / n:.2%}",
            f"{mae_band:.3f}",
        )
    console.print(table)


def _print_confusion_matrix(results: list[FixtureResult]) -> None:
    table = Table(title="Confusion matrix (rows=true, cols=predicted)")
    table.add_column("")
    for band in ALL_BANDS:
        table.add_column(band)
    table.add_column("(abstain)")
    counts: Counter[tuple[CEFRBand, CEFRBand | None]] = Counter()
    for r in results:
        counts[(r.true_band, r.predicted_band)] += 1
    for true_band in ALL_BANDS:
        row: list[str] = [true_band]
        for pred_band in ALL_BANDS:
            row.append(str(counts[(true_band, pred_band)]))
        row.append(str(counts[(true_band, None)]))
        table.add_row(*row)
    console.print(table)


def _summary(results: list[FixtureResult]) -> dict[str, float]:
    n = len(results)
    if n == 0:
        return {"accuracy": 0.0, "mae": 1.0, "band_missing": 0}
    correct = sum(1 for r in results if r.predicted_band == r.true_band)
    mae = (
        sum(
            (
                abs(
                    BAND_MIDPOINT[r.predicted_band] - BAND_MIDPOINT[r.true_band]
                )
                if r.predicted_band is not None
                else 1.0
            )
            for r in results
        )
        / n
    )
    band_missing = sum(r.band_missing for r in results)
    return {"accuracy": correct / n, "mae": mae, "band_missing": band_missing}


def _filter_fixtures(
    fixtures: list[ColdStartFixture],
    *,
    bands: tuple[CEFRBand, ...] | None,
    limit: int | None,
) -> list[ColdStartFixture]:
    if bands is not None:
        fixtures = [f for f in fixtures if f.true_band in bands]
    if limit is not None:
        fixtures = fixtures[:limit]
    return fixtures


def _load_fixtures(path: Path) -> list[ColdStartFixture]:
    raw = json.loads(path.read_text())
    fixtures: list[ColdStartFixture] = []
    for entry in raw:
        f = parse_fixture(entry)
        if isinstance(f, ColdStartFixture):
            fixtures.append(f)
    return fixtures


async def main_async(args: argparse.Namespace) -> int:
    bands_filter: tuple[CEFRBand, ...] | None = None
    if args.bands:
        valid: list[CEFRBand] = []
        for raw in args.bands.split(","):
            if raw in ALL_BANDS:
                valid.append(raw)
        bands_filter = tuple(valid)
    fixtures = _filter_fixtures(
        _load_fixtures(Path(args.fixtures)),
        bands=bands_filter,
        limit=args.limit,
    )
    if not fixtures:
        console.print("[red]no fixtures matched filter[/red]")
        return 2
    console.print(
        f"Replaying {len(fixtures)} fixtures against {args.llama_cpp_url}"
    )

    client = openai.AsyncOpenAI(
        base_url=f"{args.llama_cpp_url.rstrip('/')}/v1",
        api_key="not-used",
    )
    results: list[FixtureResult] = []
    for fixture in fixtures:
        result = await replay_fixture(
            fixture,
            client,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            no_thinking=args.no_thinking,
            verbose=args.verbose,
        )
        results.append(result)
        if args.verbose:
            console.log(
                f"{fixture.id}: true={fixture.true_band} "
                f"pred={result.predicted_band} "
                f"emitted={result.per_turn_bands}"
            )

    _print_per_fixture_table(results)
    _print_per_band_aggregate(results)
    _print_confusion_matrix(results)

    summary = _summary(results)
    console.print(
        f"\n[bold]overall[/bold] accuracy={summary['accuracy']:.2%} "
        f"MAE={summary['mae']:.3f} "
        f"band_missing={int(summary['band_missing'])}"
    )

    fail = (
        summary["accuracy"] < ACCURACY_BAR
        or summary["mae"] > MAE_BAR
    )
    if fail:
        console.print(
            f"[red]regression bar not met[/red]: "
            f"accuracy ≥ {ACCURACY_BAR:.0%} required, "
            f"MAE ≤ {MAE_BAR:.2f} required"
        )
        return 1
    console.print("[green]regression bar cleared[/green]")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Replay cold_start fixtures through llama.cpp",
    )
    p.add_argument(
        "--fixtures",
        default=str(DEFAULT_FIXTURES),
        help=f"path to cold_start fixtures (default: {DEFAULT_FIXTURES})",
    )
    p.add_argument(
        "--bands",
        default=None,
        help="comma-separated bands to filter (e.g. A1,A2)",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--llama-cpp-url",
        default=settings.llama_cpp_url,
        help=f"llama.cpp base URL (default from settings: {settings.llama_cpp_url})",
    )
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument(
        "--no-thinking",
        action="store_true",
        default=True,
        help=(
            "Pass chat_template_kwargs.enable_thinking=false (Gemma 4 "
            "thinking-mode default splits output to delta.reasoning_content)"
        ),
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
