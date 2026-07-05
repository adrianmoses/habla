"""LLM-judged second pass on recast_present.

Re-judges only the cases where the lemma-based heuristic in
``eval/scoring/recast.py`` returned False. The heuristic still misses
paraphrases that flip person across 1st/2nd/3rd, restructure the clause
significantly, or substitute a synonym. We use Claude as a tiebreaker.

Reads an existing eval JSON (produced by ``eval.run_eval``), looks at
fixtures where the lemma check failed, asks Claude to judge each one, and
writes a new JSON with ``recast_present_llm`` populated and the recast
aggregates recomputed using the LLM verdict where available. The original
heuristic field is kept so you can compare.

Usage::

    uv run python -m eval.judge_recasts \\
        --input finetuned_v3_full.json \\
        --output finetuned_v3_judged.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from rich.console import Console
from rich.progress import Progress

from eval.fixtures.schema import ColdStartFixture, Fixture, load_fixtures
from eval.scoring.turn import (
    _extract_target_forms,
    score_turn,
    strip_tool_calls,
)

console = Console()

# Stable across all judgments — placed early in the prompt for cache reuse.
JUDGE_SYSTEM = """You are evaluating a Spanish-language tutoring agent.

Your job is to decide whether the agent's reply contains a *recast* of the learner's grammatical error: the corrected form woven naturally into the agent's response, without explicit correction.

A recast counts as PRESENT if any of the following is true:
1. The agent's prose contains a grammatically correct form of the corrected token, even if conjugated differently or addressed to a different person (e.g., learner says "yo dormo" -> target "duermo", agent reflects back "tú duermes" -> PRESENT).
2. The agent paraphrases the learner's intent using a synonymous correct construction (e.g., target "es importante que estudies" -> agent "es crucial que estudies" -> PRESENT).
3. The agent uses an inflected form of the corrected lemma in any person (e.g., target "me duele la cabeza" -> agent "le duele la cabeza, pobrecita" when discussing someone else -> PRESENT).

A recast counts as ABSENT if:
- The agent deflects with a question or comment that does not model the corrected form at all.
- The agent avoids the construction entirely (e.g., target requires ser/estar but agent rephrases without either).
- The agent only echoes the learner's incorrect form, or uses a different unrelated construction.

Be strict about avoidance — if the construction is missing entirely, that's ABSENT even if the topic is on-track.

Respond with JSON: {"present": true|false, "reason": "<one short sentence>"}.
"""


class Verdict(BaseModel):
    present: bool = Field(
        description="Whether a valid recast is present in the agent reply."
    )
    reason: str = Field(description="One short sentence justifying the verdict.")


def _build_user_prompt(fixture: Fixture, model_response: str) -> str:
    last_user = next(
        (t.content for t in reversed(fixture.conversation) if t.role == "user"),
        "",
    )
    targets = _extract_target_forms(fixture)
    clean = strip_tool_calls(model_response)
    return (
        f"Learner's last message: {last_user!r}\n"
        f"Expected recast form (canonical): {fixture.expected.recast_form!r}\n"
        f"Expected corrected tokens (any inflection acceptable): {targets}\n"
        f"Agent's reply (prose only, tool calls stripped): {clean!r}\n"
        f"\nDoes the agent's reply contain a valid recast?"
    )


async def _judge_one(
    client: anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    fixture: Fixture,
    model_response: str,
) -> Verdict | None:
    user_prompt = _build_user_prompt(fixture, model_response)
    async with semaphore:
        try:
            response = await client.messages.parse(
                model="claude-opus-4-7",
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": JUDGE_SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_prompt}],
                output_format=Verdict,
            )
            return response.parsed_output
        except anthropic.APIError as e:
            console.print(f"[yellow]judge error on {fixture.id}: {e}[/yellow]")
            return None


async def _run(args: argparse.Namespace) -> None:
    load_dotenv()
    in_path = Path(args.input)
    data = json.loads(in_path.read_text())

    fixtures = {
        f.id: f
        for f in load_fixtures(Path("eval/fixtures"))
        if not isinstance(f, ColdStartFixture)
    }

    # Re-score every fixture FIRST with the current heuristic — the input
    # JSON's stored `recast_present` may be stale if the heuristic has been
    # updated since the eval ran. We want to judge based on the *current*
    # heuristic verdict, not whatever was stored months ago.
    fresh_heuristic: dict[int, bool] = {}
    for idx, r in enumerate(data["results"]):
        fx = fixtures.get(r["fixture_id"])
        if not fx:
            continue
        rescored = score_turn(fx, r["model_response"], None)
        fresh_heuristic[idx] = rescored.recast_present

    # Identify cases worth judging: current heuristic says False, and the
    # fixture has an expected form to check against.
    judge_targets: list[tuple[int, Fixture, str]] = []
    for idx, r in enumerate(data["results"]):
        fx = fixtures.get(r["fixture_id"])
        if not fx:
            continue
        if fresh_heuristic.get(idx, False):
            continue
        if fx.expected.recast_form is None and not _extract_target_forms(fx):
            continue
        judge_targets.append((idx, fx, r["model_response"]))

    n_to_judge = len(judge_targets)
    n_total = len(data["results"])
    console.print(
        f"Judging {n_to_judge}/{n_total} cases where the lemma heuristic said "
        f"recast_present=False."
    )
    if args.limit:
        judge_targets = judge_targets[: args.limit]
        console.print(
            f"[yellow]--limit {args.limit}: only judging {len(judge_targets)}[/yellow]"
        )

    client = anthropic.AsyncAnthropic()
    semaphore = asyncio.Semaphore(args.concurrency)
    verdicts: dict[int, Verdict] = {}

    with Progress() as progress:
        task = progress.add_task("Judging...", total=len(judge_targets))

        async def _go(idx: int, fx: Fixture, resp: str) -> None:
            v = await _judge_one(client, semaphore, fx, resp)
            if v is not None:
                verdicts[idx] = v
            progress.advance(task)

        await asyncio.gather(*(_go(i, f, r) for i, f, r in judge_targets))

    # Recombine: recast_present = heuristic_True OR llm_True. The LLM is a
    # tiebreaker for false negatives only — we never downgrade a heuristic
    # True to False based on the LLM, since we didn't judge the heuristic-True
    # cases.
    flipped = 0
    for idx, r in enumerate(data["results"]):
        fx = fixtures.get(r["fixture_id"])
        if not fx:
            continue
        rescored = score_turn(fx, r["model_response"], None)
        h = rescored.recast_present
        v = verdicts.get(idx)
        r["recast_present_llm"] = v.present if v else None
        if v is not None:
            r["recast_present_llm_reason"] = v.reason
        recast = h or (v.present if v else False)
        if not h and recast:
            flipped += 1
        if rescored.error_repeated:
            ped = 0.0
        else:
            signals = [
                bool(recast),
                not rescored.recast_explicit,
                rescored.register_correct,
                rescored.sentence_count_ok,
                rescored.question_count_ok,
                not rescored.L1_in_response,
            ]
            ped = sum(signals) / len(signals)
        tool_fid = (rescored.log_turn_called + rescored.tool_args_correct) / 2.0
        comp = ped * 0.7 + tool_fid * 0.3
        r["recast_present"] = bool(recast)
        r["pedagogical_score"] = round(ped, 4)
        r["tool_fidelity_score"] = round(tool_fid, 4)
        r["composite_score"] = round(comp, 4)

    out_path = Path(args.output)
    out_path.write_text(json.dumps(data, indent=2))
    n_judged = sum(
        1 for r in data["results"] if r.get("recast_present_llm") is not None
    )
    rate = sum(1 for r in data["results"] if r["recast_present"]) / len(data["results"])
    console.print(
        f"[green]Wrote {out_path}.[/green] Judged {n_judged} cases; flipped "
        f"{flipped} from False to True. New recast_present rate: {rate * 100:.2f}%"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-judge recast_present false negatives"
    )
    parser.add_argument("--input", required=True, help="Eval JSON to re-judge")
    parser.add_argument(
        "--output", required=True, help="Where to write the judged JSON"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Max concurrent Claude requests (default: 8)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of fixtures to judge (for smoke tests)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
