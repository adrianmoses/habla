"""Main eval entrypoint.

Run all standard fixtures against a model served via llama.cpp's
OpenAI-compatible API, score each response, and write results to JSON.

Usage::

    python -m eval.run_eval --base-url http://localhost:8080 --output results.json
    python -m eval.run_eval --categories single_error_recast,multi_error --output results.json
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openai
from rich.console import Console
from rich.progress import Progress

from eval.fixtures.schema import ColdStartFixture, Fixture, load_fixtures
from eval.scoring.turn import EvalOutput, TurnResult, score_turn
from finetune.format import render_system_prompt

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
    client: openai.AsyncOpenAI,
    fixture: Fixture,
    semaphore: asyncio.Semaphore,
    timeout: float,
    minimal_prompt: bool = False,
    max_tokens: int = 1024,
    no_thinking: bool = False,
) -> tuple[str, list[Any] | None]:
    """Send a fixture to the model and return (response_text, tool_calls).

    ``minimal_prompt=True`` sends only a role-setting system message. Use for
    measuring raw untuned-model baseline (no prompt engineering at all).

    ``max_tokens`` caps generation length. With Gemma 4 thinking enabled the
    model spends ~150-450 tokens on hidden reasoning before any visible
    content; 1024 leaves room for both. Drop to ~256 only when pairing with
    ``no_thinking=True``.

    ``no_thinking=True`` disables the chat template's thinking block via
    ``chat_template_kwargs={"enable_thinking": False}``. Faster and fits in
    smaller token budgets, but the model loses its error-detection step and
    will under-populate ``errors`` in tool calls.
    """
    system_content = (
        MINIMAL_SYSTEM_PROMPT
        if minimal_prompt
        else render_system_prompt(
            fixture.system_params, band=fixture.metadata.cefr_band
        )
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_content},
    ]
    for turn in fixture.conversation:
        messages.append({"role": turn.role, "content": turn.content})

    extra_body: dict[str, Any] = {}
    if no_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    async with semaphore:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gemma-4-e4b",
                messages=messages,  # type: ignore[arg-type]
                temperature=0.0,
                max_tokens=max_tokens,
                extra_body=extra_body or None,
            ),
            timeout=timeout,
        )

    choice = response.choices[0]
    text = choice.message.content or ""
    tool_calls = choice.message.tool_calls
    return text, tool_calls


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

    client = openai.AsyncOpenAI(
        base_url=args.base_url.rstrip("/") + "/v1",
        api_key="not-needed",
    )
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
                    minimal_prompt=args.minimal_prompt,
                    max_tokens=args.max_tokens,
                    no_thinking=args.no_thinking,
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
        base_url=args.base_url,
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
    parser = argparse.ArgumentParser(description="Run model eval against fixtures")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        help="llama.cpp OpenAI-compatible endpoint (default: http://localhost:8080)",
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
        "recast instructions, no tool-call schema). Use to measure the raw "
        "untuned baseline — i.e., Gemma 4 with no prompt engineering. "
        "Tool-fidelity metrics will typically be near zero in this mode.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="Max completion tokens per request (default: 1024). Gemma 4's "
        "thinking block can consume 150-450 tokens before any visible "
        "content; budgets below ~512 cause silent (empty-content) responses "
        "on harder fixtures unless paired with --no-thinking.",
    )
    parser.add_argument(
        "--no-thinking",
        action="store_true",
        help="Disable Gemma 4's chat-template thinking block via "
        "chat_template_kwargs.enable_thinking=False. ~4x faster and fits in "
        "smaller token budgets, but the model loses its error-detection "
        "step and will under-populate the `errors` field in log_turn calls.",
    )
    args = parser.parse_args()
    asyncio.run(run_eval(args))


if __name__ == "__main__":
    main()
