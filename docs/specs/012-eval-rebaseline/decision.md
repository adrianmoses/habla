# Decision Record: Eval Re-Baseline — Claude Under Test

| Field | Value |
|---|---|
| id | 012 |
| status | implemented |
| created | 2026-07-05 |
| spec | [spec.md](./spec.md) |

---

## Context

The eval harness measures recast + `log_turn` fidelity, but the *model under
test* was still Gemma over llama.cpp — both drivers (`eval/run_eval.py`,
`eval/agent/run_agent_eval.py`) called `openai.AsyncOpenAI` at `localhost:8080`
with `model="gemma-4-e4b"` and the `enable_thinking` chat-template hack. A
read-only exploration first confirmed the coupling was confined to those two
drivers: the Opus judges, the synthetic learner, `eval/scoring/*`,
`eval/fixtures/*`, and both comparators were already Anthropic/Opus-based or
model-agnostic. This slice re-points the under-test model at Claude via the
Anthropic SDK with native `log_turn` tool-calling, matching the spec-001
runtime, so the harness validates production again. Implemented on branch
`spec-eval-rebaseline-012`.

## Decision

A new shared caller `eval/claude_agent.py::call_claude` wraps
`AsyncAnthropic().messages.create` with the native `log_turn` tool (extended
thinking off; `tool_choice` unset = auto), collects text blocks into the spoken
reply, and adapts each `tool_use` block to the `{"name", "arguments"}` shape
`eval.scoring.turn.parse_tool_calls` already consumes — the same adaptation the
runtime handler uses. Both `run_eval.py::call_model` and
`run_agent_eval.py::_call_agent` delegate to it; the full-prompt path renders
with `tool_mode="native"`. The `openai` client, `base_url`, `enable_thinking`,
`gemma-4-e4b`, and the `--base-url`/`--no-thinking`/`--model-label` CLI knobs are
gone; a `--model` arg (default `settings.llm_model_name` = `claude-sonnet-4-6`)
replaces them, and the outputs record the model id instead of a `base_url`.
Judges, synthetic learner, scoring, fixtures, and comparators are unchanged.

---

## Alternatives Considered

### Native tool-calling vs text-form emission for the under-test model

**Native `tool_use`, mirroring the runtime (chosen).** Render `tool_mode="native"`,
register the `log_turn` Anthropic tool, read the structured block.
- Pros: eval measures exactly what production does (spec 001's runtime path); the
  structured `parse_tool_calls` path is already there; retires the Gemma-only
  text regex for eval.
- Cons: none material — it's the faithful choice.

**Keep text-form emission (`tool_mode="text"`) + the regex parser.** Rejected —
production doesn't emit `log_turn` as text anymore, so text-form eval would
measure a behaviour the runtime no longer has.

### Where the under-test caller lives

**One shared `call_claude` in `eval/` (chosen).** `call_model` and `_call_agent`
were already parallel (build `system` + messages → call → return `(text,
tool_calls)`), so one helper replaces both OpenAI calls and is the single
offline-testable unit. Inlining the block-adaptation twice was the rejected
alternative.

### `EvalOutput`/`AgentEvalOutput` model field

**Rename `EvalOutput.base_url` → `model`; drop `AgentEvalOutput.base_url`, keep
`model_label` (chosen).** Grep confirmed nothing reads `base_url` and no test
constructs these, so the rename is safe. `AgentEvalOutput` already had a
`model_label` (used by `eval/agent/compare.py`), so dropping `base_url` and
feeding `model_label` from `--model` kept `SessionRecord`/`compare.py` untouched.

### Judge / synthetic-learner model

**Leave on `claude-opus-4-7` (chosen, deferred bump).** Bumping to current Opus
would silently reuse stale disk-cached verdicts (the cache keys hash
`JUDGE_SYSTEM_VERSION`/`LEARNER_SYSTEM_VERSION` + transcript, not the model id),
so it needs a version bump to invalidate — its own change, out of this slice.

---

## Tradeoffs

- **Eval now bills Anthropic for the under-test model too** (previously free
  local Gemma). The under-test path is deliberately uncached (measuring fresh);
  `_cost_preview` gained a rough Sonnet per-turn term.
- **The live smoke runs locally on every `pytest`** — `config.py`'s import-time
  `load_dotenv` (spec 009) re-populates `ANTHROPIC_API_KEY` from `.env`, so the
  `skipif` doesn't skip locally. Cheap (one short call), and CI skips it (no
  `.env`). Same behaviour as the pre-existing `test_agent_*_smoke.py`.
- **Vestigial text-form tool parsing kept** in `eval/scoring/turn.py` — harmless,
  and still lets `parse_tool_calls` score raw text; a future cleanup.
- **Temperature 0.0** for eval stability (the runtime uses 0.7) — the recast /
  `log_turn` behaviour under test is robust to it.

---

### Spec Divergence

The implementation matched the spec. One structural detail resolved during
implementation, not a divergence in intent:

| Spec Said | What Was Built | Reason |
|---|---|---|
| "record the model id instead of `base_url`" | `EvalOutput.base_url` → `model`; `AgentEvalOutput` **drops** `base_url` and reuses its existing `model_label` | `AgentEvalOutput` already had `model_label` (read by `compare.py`); reusing it avoided touching `SessionRecord`/`compare.py`. The spec explicitly allowed "rename to `model` / reuse `model_label`". |

The live smoke drives `call_claude` with a rendered native prompt rather than a
fixture — because there are **no committed fixture JSONs** (they're batch-
generated). Noted below; not a spec change.

---

## Spec Gaps Exposed

- **No fixture JSONs are committed** — `eval/fixtures/*.json` are generated by
  `scripts/fixtures/generate_fixtures.py` (Anthropic Batches API) and were never
  tracked, so `run_eval.py`'s fixture path is dormant until they're regenerated.
  `load_fixtures` tolerates their absence (returns `[]`). The agent-eval path has
  committed personas and is fully exercisable. Regenerating fixtures for the
  cloud model is a candidate follow-up (not #012 scope).
- **Judge/learner disk-cache keys omit the model id** — flagged for whoever bumps
  those models: bump the `*_SYSTEM_VERSION` constants to invalidate.

---

## Test Evidence

Offline gates (spaCy `es_core_news_sm` present):

```
$ uv run pytest -q
258 passed, 52 skipped, 9 warnings in 14.48s

$ uv run ruff check hable_ya api eval/agent eval/run_eval.py eval/claude_agent.py tests scripts
All checks passed!

$ uv run mypy hable_ya api eval/agent eval/run_eval.py eval/claude_agent.py
Success: no issues found in 56 source files
```

`tests/test_eval_claude_agent.py` (offline) asserts `call_claude` collects text
blocks and adapts a `tool_use` block into a `{"name":"log_turn","arguments":…}`
that `parse_tool_calls` accepts.

Live proof — the model-under-test path against the real Anthropic API
(`tests/test_eval_claude_smoke.py`, which executed rather than skipping because
`.env` supplied the key):

```
tests/test_eval_claude_smoke.py . [100%]   (1 passed in 4.01s)
```

A ~4s duration (vs. an instant skip) confirms a live call: Claude both replied
in Spanish and emitted a native `log_turn` tool call under the eval prompt with
`settings.llm_model_name` — the direct evidence the re-baselined harness measures
the cloud runtime.
