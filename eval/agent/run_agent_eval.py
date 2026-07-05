"""Agent-eval orchestrator.

Runs one session per authored persona end-to-end:

1. Load personas from `eval/agent/personas/*.json`.
2. For each persona, simulate a session: alternate (learner, agent) turns
   up to `turn_budget`. The learner is `SyntheticLearner` (Opus); the
   agent is the served llama.cpp model called via the OpenAI-compatible
   `/v1/chat/completions` endpoint, prompted via the *same*
   `finetune.format.render_system_prompt` the runtime uses.
3. After each agent turn, parse `log_turn` from the response and feed the
   resulting `TurnRecord` to the in-process `ProfileAccumulator` so the
   next turn's system prompt reflects the evolving learner profile.
4. After the session, hand the full transcript + persona to
   `eval.agent.opus_judge.judge_session` for a 5-dim `SessionVerdict`.
5. Aggregate by dimension, band, and persona error_pattern; write
   `agent_results.json` shaped after `eval.run_eval.EvalOutput`.

Both Opus calls (learner + judge) are disk-cached. First-run cost ~$4
per the spec; cached re-runs are free.
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
import openai
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress

from eval.agent._cache import JsonDiskCache
from eval.agent.accumulator import ProfileAccumulator
from eval.agent.opus_judge import judge_session
from eval.agent.personas.schema import Persona, load_personas
from eval.agent.synthetic_learner import SyntheticLearner
from eval.agent.synthetic_learner import _cache_key as _learner_cache_key
from eval.agent.types import (
    AgentEvalOutput,
    ConversationTurn,
    SessionRecord,
    TurnRecord,
)
from eval.fixtures.schema import CEFRBand, FluencySignal, SystemParams, Theme
from eval.run_eval import MINIMAL_SYSTEM_PROMPT
from eval.scoring.recast import content_lemma_surfaces
from eval.scoring.turn import parse_tool_calls, strip_tool_calls
from finetune.format import render_system_prompt
from hable_ya.learner.aggregations import LearnerProfileSnapshot
from hable_ya.learner.bands import is_valid_cefr_band
from hable_ya.learner.profile import snapshot_to_profile
from hable_ya.learner.themes import THEMES_BY_LEVEL

console = Console()

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_CACHE_DIR = Path(".cache/agent_eval")
DEFAULT_PERSONAS_DIR = Path("eval/agent/personas")
DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_MAX_TOKENS = 1024
LLAMA_MODEL_ID = "gemma-4-e4b"

# Per spec OQ#6 cost table: short Opus learner turn (~$15/Mtok in,
# $75/Mtok out) averages ~$0.018; one judge call (full transcript +
# rubric) averages ~$0.06. Used by `_cost_preview` only.
COST_PER_LEARNER_TURN_USD = 0.018
COST_PER_JUDGE_CALL_USD = 0.06

# Single source of truth for the 5 session-level dimension names. Shared
# with `eval.agent.compare` so the two grouping orders cannot drift.
DIMENSION_KEYS: tuple[str, ...] = (
    "pedagogical_flow",
    "level_consistency",
    "recast_naturalness",
    "learner_production_space",
    "coherence",
)

_VALID_FLUENCY: set[FluencySignal] = {"weak", "moderate", "strong"}


def _theme_for_persona(persona: Persona) -> Theme:
    for t in THEMES_BY_LEVEL[persona.cefr_band]:
        if t.domain == persona.scenario_domain:
            return t
    raise RuntimeError(
        f"persona {persona.id!r}: scenario {persona.scenario_domain!r} "
        f"not registered in THEMES_BY_LEVEL[{persona.cefr_band}]"
    )


def _build_agent_system_prompt(
    persona: Persona,
    snapshot: LearnerProfileSnapshot,
    *,
    minimal: bool,
) -> str:
    if minimal:
        return MINIMAL_SYSTEM_PROMPT
    profile = snapshot_to_profile(snapshot)
    theme = _theme_for_persona(persona)
    return render_system_prompt(
        SystemParams(profile=profile, theme=theme), band=persona.cefr_band
    )


async def _call_agent(
    client: openai.AsyncOpenAI,
    *,
    system_prompt: str,
    transcript: list[ConversationTurn],
    timeout: float,
    max_tokens: int,
    no_thinking: bool,
) -> tuple[str, list[Any] | None]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]
    for t in transcript:
        messages.append({"role": t.role, "content": t.content})

    extra_body: dict[str, Any] = {}
    if no_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=LLAMA_MODEL_ID,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.0,
            max_tokens=max_tokens,
            extra_body=extra_body or None,
        ),
        timeout=timeout,
    )
    choice = response.choices[0]
    text = choice.message.content or ""
    return text, choice.message.tool_calls


def _build_turn_record(
    parsed_calls: list[dict[str, Any]],
    learner_utterance: str,
) -> TurnRecord | None:
    """Extract a `TurnRecord` from the agent's `log_turn` call.

    Returns `None` if the agent did not emit a parseable `log_turn` —
    per project memory, ~20% of turns miss it on deployed Gemma. The
    accumulator skips those turns (see ProfileAccumulator).
    """
    log_turn = next(
        (c for c in parsed_calls if c.get("name") == "log_turn"), None
    )
    if log_turn is None:
        return None
    args = log_turn.get("arguments", {}) or {}

    raw_fluency = args.get("fluency_signal", "moderate")
    fluency: FluencySignal = (
        raw_fluency if raw_fluency in _VALID_FLUENCY else "moderate"
    )

    error_categories: list[str] = []
    for err in args.get("errors", []):
        if isinstance(err, dict) and "type" in err:
            error_categories.append(str(err["type"]))

    lemmas = [pair[0] for pair in content_lemma_surfaces(learner_utterance)]
    raw_band = args.get("cefr_band")
    cefr_band: CEFRBand | None = raw_band if is_valid_cefr_band(raw_band) else None
    return TurnRecord(
        fluency_signal=fluency,
        L1_used=bool(args.get("L1_used", False)),
        error_categories=error_categories,
        vocab_lemmas=lemmas,
        cefr_band=cefr_band,
    )


async def simulate_session(
    persona: Persona,
    learner: SyntheticLearner,
    agent_client: openai.AsyncOpenAI,
    accumulator: ProfileAccumulator,
    *,
    max_turns: int,
    minimal_prompt: bool,
    no_thinking: bool,
    timeout: float,
    max_tokens: int,
) -> tuple[list[ConversationTurn], list[TurnRecord], float]:
    """Drive one persona to `max_turns` learner turns.

    Each iteration: learner speaks (cached or live), agent responds,
    parse log_turn, feed accumulator. Loop terminates on turn budget or
    on any agent-side error (recorded into the verdict via the judge's
    post-hoc `stop_reason`).
    """
    transcript: list[ConversationTurn] = []
    turn_records: list[TurnRecord] = []
    start = time.monotonic()

    for _ in range(max_turns):
        try:
            learner_utt = await learner.next_utterance(transcript)
        except anthropic.APIError as e:
            console.print(
                f"[yellow]learner error in {persona.id}: {e}[/yellow]"
            )
            break
        transcript.append(ConversationTurn(role="user", content=learner_utt))

        snapshot = accumulator.snapshot()
        system_prompt = _build_agent_system_prompt(
            persona, snapshot, minimal=minimal_prompt
        )
        try:
            agent_text, tool_calls = await _call_agent(
                agent_client,
                system_prompt=system_prompt,
                transcript=transcript,
                timeout=timeout,
                max_tokens=max_tokens,
                no_thinking=no_thinking,
            )
        except Exception as e:
            console.print(
                f"[yellow]agent call failed in {persona.id}: {e}[/yellow]"
            )
            break

        clean_text = strip_tool_calls(agent_text)
        transcript.append(
            ConversationTurn(role="assistant", content=clean_text)
        )

        parsed = parse_tool_calls(agent_text, tool_calls)
        record = _build_turn_record(parsed, learner_utt)
        if record is not None:
            accumulator.ingest(record, observed_at=datetime.now(UTC))
            turn_records.append(record)

    elapsed = time.monotonic() - start
    return transcript, turn_records, elapsed


def compute_agent_aggregates(
    sessions: list[SessionRecord],
) -> dict[str, Any]:
    """Aggregate verdicts by dimension, band, and persona error_pattern.

    Shape parallels `eval.run_eval.compute_aggregates`: one block per
    grouping with rounded means and counts. Empty input → empty dict.
    """
    if not sessions:
        return {}

    n = len(sessions)

    overall_scores = [s.verdict.overall for s in sessions]
    overall = {
        "mean": round(sum(overall_scores) / n, 4),
        "n": n,
    }

    by_dimension: dict[str, dict[str, Any]] = {}
    for dim in DIMENSION_KEYS:
        scores = [getattr(s.verdict, dim) for s in sessions]
        by_dimension[dim] = {
            "mean": round(sum(scores) / n, 4),
            "n": n,
        }

    bands = sorted({s.cefr_band for s in sessions})
    by_band: dict[str, dict[str, Any]] = {}
    for band in bands:
        band_sessions = [s for s in sessions if s.cefr_band == band]
        bn = len(band_sessions)
        by_band[band] = {
            "overall_mean": round(
                sum(s.verdict.overall for s in band_sessions) / bn, 4
            ),
            "n": bn,
        }

    pattern_to_overalls: dict[str, list[float]] = {}
    for s in sessions:
        for pattern in s.error_patterns:
            pattern_to_overalls.setdefault(pattern, []).append(s.verdict.overall)
    by_error_pattern: dict[str, dict[str, Any]] = {}
    for pattern, scores in sorted(pattern_to_overalls.items()):
        by_error_pattern[pattern] = {
            "overall_mean": round(sum(scores) / len(scores), 4),
            "n": len(scores),
        }

    stop_reasons: dict[str, int] = {}
    for s in sessions:
        stop_reasons[s.verdict.stop_reason] = (
            stop_reasons.get(s.verdict.stop_reason, 0) + 1
        )

    return {
        "overall": overall,
        "by_dimension": by_dimension,
        "by_band": by_band,
        "by_error_pattern": by_error_pattern,
        "stop_reasons": stop_reasons,
    }


def _filter_personas(personas: list[Persona], pattern: str) -> list[Persona]:
    """Glob-or-comma filter on persona id."""
    parts = [p.strip() for p in pattern.split(",") if p.strip()]
    selected: list[Persona] = []
    for p in personas:
        if any(fnmatch.fnmatch(p.id, part) for part in parts):
            selected.append(p)
    return selected


def _cost_preview(
    personas: list[Persona],
    learner_cache: JsonDiskCache,
) -> dict[str, Any]:
    """Worst-case cost estimate from observable cache state.

    Only the first learner turn has a deterministic cache key, so
    judge calls and downstream learner turns are always assumed
    uncached. See spec OQ#6 — first-run ~$4 for 15×12 turns.
    """
    learner_uncached = 0
    for p in personas:
        if p.opening_utterance:
            continue
        first_key = _learner_cache_key(p.id, [])
        if not learner_cache.has(first_key):
            learner_uncached += 1

    avg_turns = sum(p.turn_budget for p in personas) / max(1, len(personas))
    learner_cost = learner_uncached * avg_turns * COST_PER_LEARNER_TURN_USD
    judge_cost = len(personas) * COST_PER_JUDGE_CALL_USD
    total = learner_cost + judge_cost

    return {
        "personas": len(personas),
        "avg_turn_budget": round(avg_turns, 1),
        "learner_uncached_first_turn": learner_uncached,
        "estimate_usd_worst_case": round(total, 2),
    }


async def run_agent_eval(args: argparse.Namespace) -> AgentEvalOutput:
    load_dotenv()
    cache_dir = Path(args.cache_dir)
    learner_cache = JsonDiskCache(cache_dir, key_prefix="learner_")
    judge_cache = JsonDiskCache(cache_dir, key_prefix="judge_")

    personas_dir = Path(args.personas_dir)
    personas = load_personas(personas_dir)
    if args.personas:
        personas = _filter_personas(personas, args.personas)
    if args.limit is not None:
        personas = personas[: args.limit]

    if not personas:
        console.print("[red]No personas selected; nothing to do.[/red]")
        return AgentEvalOutput(
            run_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC).isoformat(),
            base_url=args.base_url,
            model_label=args.model_label,
            session_count=0,
            sessions=[],
            aggregates={},
        )

    preview = _cost_preview(personas, learner_cache)
    console.print(
        f"[cyan]Cost preview ({preview['personas']} personas, "
        f"avg {preview['avg_turn_budget']} turns):[/cyan] "
        f"learner uncached first-turn="
        f"{preview['learner_uncached_first_turn']}, "
        f"worst-case ~${preview['estimate_usd_worst_case']}"
    )

    if args.dry_run:
        console.print("[yellow]--dry-run set; skipping API calls[/yellow]")
        for p in personas:
            theme = _theme_for_persona(p)
            console.print(f"  • {p.id} → band={p.cefr_band} theme={theme.domain}")
        return AgentEvalOutput(
            run_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC).isoformat(),
            base_url=args.base_url,
            model_label=args.model_label,
            session_count=0,
            sessions=[],
            aggregates={},
        )

    llama_client = openai.AsyncOpenAI(
        base_url=args.base_url.rstrip("/") + "/v1",
        api_key="not-needed",
    )
    anthropic_client = anthropic.AsyncAnthropic()
    semaphore = asyncio.Semaphore(args.concurrency)

    sessions: list[SessionRecord] = []
    errors: list[str] = []

    async def run_one(persona: Persona) -> None:
        async with semaphore:
            learner = SyntheticLearner(
                persona, anthropic_client, cache=learner_cache
            )
            accumulator = ProfileAccumulator(persona)
            try:
                transcript, turn_records, elapsed = await simulate_session(
                    persona,
                    learner,
                    llama_client,
                    accumulator,
                    max_turns=persona.turn_budget,
                    minimal_prompt=args.minimal_prompt,
                    no_thinking=args.no_thinking,
                    timeout=args.timeout,
                    max_tokens=args.max_tokens,
                )
                verdict = await judge_session(
                    anthropic_client,
                    persona,
                    transcript,
                    cache=judge_cache,
                )
                sessions.append(
                    SessionRecord(
                        persona_id=persona.id,
                        cefr_band=persona.cefr_band,
                        scenario_domain=persona.scenario_domain,
                        error_patterns=list(persona.error_patterns),
                        transcript=transcript,
                        turn_records=turn_records,
                        verdict=verdict,
                        model_label=args.model_label,
                        elapsed_s=round(elapsed, 2),
                    )
                )
            except Exception as e:
                errors.append(f"{persona.id}: {e}")

    with Progress() as progress:
        task = progress.add_task("Running sessions...", total=len(personas))

        async def go(p: Persona) -> None:
            await run_one(p)
            progress.advance(task)

        await asyncio.gather(*(go(p) for p in personas))

    if errors:
        console.print(f"\n[yellow]{len(errors)} sessions failed:[/yellow]")
        for err in errors[:5]:
            console.print(f"  {err}")

    aggregates = compute_agent_aggregates(sessions)
    output = AgentEvalOutput(
        run_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        base_url=args.base_url,
        model_label=args.model_label,
        session_count=len(sessions),
        sessions=sessions,
        aggregates=aggregates,
    )
    out_path = Path(args.output)
    out_path.write_text(output.model_dump_json(indent=2))
    console.print(
        f"\n[green]Wrote {out_path}[/green] — {len(sessions)} sessions, "
        f"overall={aggregates.get('overall', {}).get('mean', 'N/A')}"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run session-level agent eval against llama.cpp + Opus."
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"llama.cpp endpoint (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"Disk cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--personas-dir",
        type=Path,
        default=DEFAULT_PERSONAS_DIR,
        help="Directory of persona JSON files",
    )
    parser.add_argument(
        "--personas",
        default=None,
        help="Glob/comma persona-id filter, e.g. 'a1_*,a2_ser_*'",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap total sessions",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max concurrent sessions (default: {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"Per-agent-call timeout in s (default: {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Max completion tokens per agent call (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--minimal-prompt",
        action="store_true",
        help="Send only the role-setting system prompt (baseline mode).",
    )
    parser.add_argument(
        "--no-thinking",
        action="store_true",
        help="Disable Gemma thinking via chat_template_kwargs.",
    )
    parser.add_argument(
        "--model-label",
        default=LLAMA_MODEL_ID,
        help="Label stored in each session record + aggregate report.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve personas and themes, log the plan, hit no endpoint.",
    )
    args = parser.parse_args()
    asyncio.run(run_agent_eval(args))


if __name__ == "__main__":
    main()
