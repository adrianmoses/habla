"""Main eval entrypoint.

Run all standard fixtures against Claude via the Anthropic API — the same native
`log_turn` tool contract the runtime uses — score each response, and write
results to JSON.

Usage::

    python -m eval.run_eval --output results.json
    python -m eval.run_eval --model claude-sonnet-4-6 --categories single_error_recast --output results.json
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
from rich.console import Console
from rich.progress import Progress

from eval.claude_agent import call_claude
from eval.fixtures.schema import ColdStartFixture, Fixture, load_fixtures
from eval.scoring.turn import EvalOutput, TurnResult, score_turn
from hable_ya.config import settings
from hable_ya.pipeline.prompts.render import render_system_prompt

console = Console()

# Used when --minimal-prompt is set. Just role-sets the model — no register
# rules, no recast instructions, no tool-call schema, no forbidden phrases.
# This is the "unprompted baseline" mode: what does the raw model do when
# you only tell it what role to play?
MINIMAL_SYSTEM_PROMPT = "You are a Spanish conversation partner for a language learner."

# ---------------------------------------------------------------------------
# Model calling
# ---------------------------------------------------------------------------


async def call_model(
    client: anthropic.AsyncAnthropic,
    fixture: Fixture,
    semaphore: asyncio.Semaphore,
    timeout: float,
    model: str,
    minimal_prompt: bool = False,
    max_tokens: int = 1024,
) -> tuple[str, list[dict[str, Any]]]:
    """Send a fixture to Claude and return (response_text, tool_calls).

    ``minimal_prompt=True`` sends only a role-setting system message — the
    unprompted baseline (no register rules, recast instructions, or tool
    guidance). Use to measure how much the runtime prompt engineering buys.

    The full-prompt path renders with ``tool_mode="native"`` and Claude emits
    ``log_turn`` as a native tool call (see ``eval.claude_agent.call_claude``).
    """
    system_content = (
        MINIMAL_SYSTEM_PROMPT
        if minimal_prompt
        else render_system_prompt(
            fixture.system_params,
            band=fixture.metadata.cefr_band,
            tool_mode="native",
        )
    )
    messages: list[dict[str, str]] = [
        {"role": turn.role, "content": turn.content}
        for turn in fixture.conversation
    ]

    async with semaphore:
        return await asyncio.wait_for(
            call_claude(
                client,
                model=model,
                system=system_content,
                messages=messages,
                max_tokens=max_tokens,
            ),
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

_DIMENSION_FIELDS = [
    "recast_present",
    "recast_explicit",
    "register_correct",
    "sentence_count_ok",
    "question_count_ok",
    "L1_in_response",
    "error_repeated",
]

_INVERTED = {"recast_explicit", "L1_in_response", "error_repeated"}


def compute_aggregates(results: list[TurnResult]) -> dict[str, Any]:
    """Compute aggregate scores by dimension, band, and category."""
    n = len(results)
    if n == 0:
        return {}

    # Overall
    overall = {
        "pedagogical": round(sum(r.pedagogical_score for r in results) / n, 4),
        "tool_fidelity": round(sum(r.tool_fidelity_score for r in results) / n, 4),
        "composite": round(sum(r.composite_score for r in results) / n, 4),
        "n": n,
    }

    # By dimension — rate is the fraction where the signal fired
    by_dimension: dict[str, Any] = {}
    for field in _DIMENSION_FIELDS:
        count = sum(1 for r in results if getattr(r, field))
        rate = round(count / n, 4)
        by_dimension[field] = {"rate": rate, "n": n}
    by_dimension["log_turn_called"] = {
        "rate": round(sum(1 for r in results if r.log_turn_called) / n, 4),
        "n": n,
    }
    by_dimension["tool_args_correct"] = {
        "rate": round(sum(1 for r in results if r.tool_args_correct) / n, 4),
        "n": n,
    }

    # By band
    bands = sorted({r.cefr_band for r in results})
    by_band: dict[str, Any] = {}
    for band in bands:
        band_results = [r for r in results if r.cefr_band == band]
        bn = len(band_results)
        by_band[band] = {
            "pedagogical": round(
                sum(r.pedagogical_score for r in band_results) / bn, 4
            ),
            "tool_fidelity": round(
                sum(r.tool_fidelity_score for r in band_results) / bn, 4
            ),
            "composite": round(sum(r.composite_score for r in band_results) / bn, 4),
            "n": bn,
        }

    # By category
    categories = sorted({r.category for r in results})
    by_category: dict[str, Any] = {}
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        cn = len(cat_results)
        by_category[cat] = {
            "pedagogical": round(sum(r.pedagogical_score for r in cat_results) / cn, 4),
            "composite": round(sum(r.composite_score for r in cat_results) / cn, 4),
            "n": cn,
        }

    return {
        "overall": overall,
        "by_dimension": by_dimension,
        "by_band": by_band,
        "by_category": by_category,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_eval(args: argparse.Namespace) -> EvalOutput:
    """Run the full eval pipeline."""
    fixtures_path = Path("eval/fixtures")
    all_fixtures = load_fixtures(fixtures_path)

    # Split standard vs cold start
    standard: list[Fixture] = []
    cold_start_count = 0
    for f in all_fixtures:
        if isinstance(f, ColdStartFixture):
            cold_start_count += 1
        else:
            standard.append(f)

    # Filter by category if requested
    if args.categories:
        cats = {c.strip() for c in args.categories.split(",")}
        standard = [f for f in standard if any(f.id.startswith(cat) for cat in cats)]

    prompt_mode = "minimal (baseline)" if args.minimal_prompt else "engineered"
    console.print(
        f"Running eval: {len(standard)} standard fixtures "
        f"(skipping {cold_start_count} cold start) — prompt mode: {prompt_mode}"
    )

    client = anthropic.AsyncAnthropic()
    semaphore = asyncio.Semaphore(args.concurrency)

    results: list[TurnResult] = []
    errors: list[str] = []

    with Progress() as progress:
        task = progress.add_task("Evaluating fixtures...", total=len(standard))

        async def process_fixture(fixture: Fixture) -> None:
            try:
                response_text, tool_calls = await call_model(
                    client,
                    fixture,
                    semaphore,
                    args.timeout,
                    model=args.model,
                    minimal_prompt=args.minimal_prompt,
                    max_tokens=args.max_tokens,
                )
                result = score_turn(fixture, response_text, tool_calls)
                results.append(result)
            except Exception as e:
                errors.append(f"{fixture.id}: {e}")
            finally:
                progress.advance(task)

        await asyncio.gather(*(process_fixture(f) for f in standard))

    if errors:
        console.print(f"\n[yellow]{len(errors)} fixtures failed:[/yellow]")
        for err in errors[:10]:
            console.print(f"  {err}")
        if len(errors) > 10:
            console.print(f"  ... and {len(errors) - 10} more")

    aggregates = compute_aggregates(results)

    output = EvalOutput(
        run_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        model=args.model,
        fixture_count=len(standard),
        cold_start_skipped=cold_start_count,
        results=results,
        errors=errors,
        aggregates=aggregates,
    )

    out_path = Path(args.output)
    out_path.write_text(output.model_dump_json(indent=2))
    console.print(f"\n[green]Results written to {out_path}[/green]")
    console.print(
        f"Composite: {aggregates.get('overall', {}).get('composite', 'N/A')} "
        f"(n={len(results)})"
    )

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claude eval against fixtures")
    parser.add_argument(
        "--model",
        default=settings.llm_model_name,
        help=f"Claude model under test (default: {settings.llm_model_name})",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path for output JSON file",
    )
    parser.add_argument(
        "--categories",
        default=None,
        help="Comma-separated category filter (default: all)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max concurrent requests (default: 4)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Per-request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--minimal-prompt",
        action="store_true",
        help="Send only a role-setting system prompt (no register rules, no "
        "recast instructions, no tool-call schema). Use to measure the "
        "unprompted baseline — how much the runtime prompt engineering buys. "
        "Tool-fidelity metrics will typically be near zero in this mode.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="Max completion tokens per request (default: 1024) — room for a "
        "short reply plus the native log_turn tool-call args.",
    )
    args = parser.parse_args()
    asyncio.run(run_eval(args))


if __name__ == "__main__":
    main()
