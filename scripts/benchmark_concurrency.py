"""Diagnose whether the eval client + llama.cpp server are actually running
concurrently. Fires 8 requests sequentially then 8 concurrently against the
same endpoint; prints wall-time speedup.

Run (server must be up)::

    uv run python -m scripts.benchmark_concurrency
    uv run python -m scripts.benchmark_concurrency --base-url http://localhost:8080 --n 8

Interpretation:
- speedup ~3-4x: client + server are cooperating, server parallel slots working.
- speedup ~1x: something is serializing even though server reports n_slots > 1.
- speedup ~2x: partial parallelism; usually GPU memory pressure or overhead.
"""

from __future__ import annotations

import argparse
import asyncio
import time

import openai

TINY_PROMPT = "Responde en español: ¿Cómo te llamas?"


def _realistic_messages() -> list[dict[str, str]]:
    """Mirror what eval.run_eval sends: a full rendered system prompt + a few
    conversation turns. Uses the first standard fixture so the size and shape
    are representative of real eval load.
    """
    from pathlib import Path

    from eval.fixtures.schema import Fixture, load_fixtures
    from finetune.format import render_system_prompt

    fixtures = [
        f for f in load_fixtures(Path("eval/fixtures")) if isinstance(f, Fixture)
    ]
    fx = fixtures[0]
    msgs: list[dict[str, str]] = [
        {
            "role": "system",
            "content": render_system_prompt(
                fx.system_params, band=fx.metadata.cefr_band
            ),
        },
    ]
    for turn in fx.conversation:
        msgs.append({"role": turn.role, "content": turn.content})
    return msgs


async def one_call(
    client: openai.AsyncOpenAI,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    idx: int,
) -> tuple[int, float]:
    t0 = time.time()
    await client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return idx, time.time() - t0


async def run(base_url: str, model: str, n: int, realistic: bool) -> None:
    client = openai.AsyncOpenAI(
        base_url=base_url.rstrip("/") + "/v1",
        api_key="not-needed",
    )

    if realistic:
        messages = _realistic_messages()
        max_tokens = 512
        sys_len = len(messages[0]["content"])
        print(
            f"mode: realistic  (system prompt ~{sys_len // 4} tokens, "
            f"max_tokens={max_tokens})"
        )
    else:
        messages = [{"role": "user", "content": TINY_PROMPT}]
        max_tokens = 40
        print(f"mode: tiny  (tiny prompt, max_tokens={max_tokens})")
    print()

    # Warm-up so the first call doesn't skew the sequential measurement
    # and so any prefix cache is primed.
    await one_call(client, model, messages, max_tokens, -1)

    # Sequential: one call at a time.
    t0 = time.time()
    for i in range(n):
        await one_call(client, model, messages, max_tokens, i)
    seq = time.time() - t0
    print(f"sequential {n}x : {seq:6.2f}s total   {seq / n:.2f}s per call")

    # Concurrent: all N in flight.
    t0 = time.time()
    results = await asyncio.gather(
        *(one_call(client, model, messages, max_tokens, i) for i in range(n))
    )
    conc = time.time() - t0
    avg = sum(d for _, d in results) / n
    print(f"concurrent {n}x : {conc:6.2f}s total   avg {avg:.2f}s per call")

    speedup = seq / conc if conc > 0 else 0.0
    print(f"\nspeedup       : {speedup:.2f}x")
    if realistic:
        print("(expect ~3-4x — this is the load eval.run_eval actually sends)")
    else:
        print("(tiny prompts don't predict eval speedup well; try --realistic)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--model", default="gemma-4-e4b")
    parser.add_argument(
        "--n",
        type=int,
        default=8,
        help="how many calls to fire for each mode (default: 8)",
    )
    parser.add_argument(
        "--realistic",
        action="store_true",
        help="Use an eval-sized prompt (rendered system prompt + conversation) "
        "with max_tokens=512, instead of a tiny toy prompt. This is what the "
        "real eval load looks like.",
    )
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.model, args.n, args.realistic))


if __name__ == "__main__":
    main()
