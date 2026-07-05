# Spec: Eval Re-Baseline — Claude Under Test

| Field | Value |
|---|---|
| id | 012 |
| status | approved |
| created | 2026-07-05 |
| covers roadmap | #012 |

---

## Why

The eval harness measures whether the model reproduces the two behaviours the
product depends on — recasting learner errors and emitting a well-formed
`log_turn` — but the **model under test is still the on-device Gemma over
llama.cpp**. Both entrypoints (`eval/run_eval.py`, `eval/agent/run_agent_eval.py`)
call `openai.AsyncOpenAI` against `localhost:8080` with `model="gemma-4-e4b"` and
the Gemma `enable_thinking` chat-template hack. Since the runtime moved to Claude
with native tool-calling (spec 001), the eval no longer measures what production
does — the recast/`log_turn` quality signal has been dead since the swap.

This slice re-points the model-under-test at **Claude via the Anthropic SDK with
native tool-calling**, matching the runtime exactly, so the harness validates the
real cloud agent again. Everything else in `eval/` — the Opus judges, synthetic
learner, scoring heuristics, fixtures, comparators — is already Claude/Opus-based
or model-agnostic and carries over untouched.

### Consumer Impact

- **Project owner:** Gets a working eval against the actual cloud runtime — can
  answer "does Claude + the runtime prompt reproduce natural recasts and reliable
  `log_turn` emission?" (the whole point of the harness), and re-run it as the
  prompt/model evolves. The `--minimal-prompt` ablation is re-purposed from
  "untuned vs fine-tuned Gemma" to "Claude minimal vs Claude full-runtime-prompt"
  — i.e. how much the prompt engineering buys, which is the cloud analog of the
  old baseline-vs-finetuned question.
- **End user (learner):** No change (eval is offline tooling).
- **Downstream:** #013 (latency) can reuse the Claude-under-test caller; the
  harness becomes the place to catch pedagogy regressions when the prompt or model
  changes.

### Roadmap Fit

Roadmap #012. Upstream: spec 001 (Claude runtime + native `log_turn` tool-calling
+ the `tool_mode` prompt flag), spec 010 (`anthropic` in core). Downstream: none
blocked; #015 (docs) will describe the cloud eval. The exploration confirmed the
coupling is confined to the two under-test drivers — the judges/learner/scoring
were always separate Anthropic/agnostic components.

---

## What

### Acceptance Criteria

- [ ] `eval/run_eval.py` and `eval/agent/run_agent_eval.py` invoke the
  **model under test via `anthropic.AsyncAnthropic`** (not `openai.AsyncOpenAI` /
  a llama.cpp endpoint). The `openai` client, `base_url`, `api_key="not-needed"`,
  `LLAMA_MODEL_ID`, `DEFAULT_BASE_URL`, and the `chat_template_kwargs.enable_thinking`
  `extra_body` are removed.
- [ ] The under-test model is **configurable, defaulting to the runtime model**
  (`settings.llm_model_name`, i.e. `claude-sonnet-4-6`), via a `--model` CLI arg.
  Extended thinking is disabled and `max_tokens` mirrors the runtime — same
  latency posture as production.
- [ ] The under-test call uses **native tool-calling**: `log_turn` is registered
  as an Anthropic tool (`tool_choice` unset = auto, as in the runtime), and the
  full-prompt path renders with `render_system_prompt(..., tool_mode="native")`.
  `log_turn` is read from the response's `tool_use` block and fed through
  `parse_tool_calls(text, api_tool_calls=…)`'s **structured path** (the same
  `{"name", "arguments"}` adapter the runtime handler uses) — no text-form regex.
- [ ] A single Anthropic `log_turn` tool definition lives in
  `hable_ya/tools/schema.py` (`LOG_TURN_ANTHROPIC_TOOL`, built from the existing
  `LOG_TURN_PROPERTIES`/`LOG_TURN_REQUIRED`) so eval and any future direct-SDK
  caller share one source (the runtime uses the pipecat `FunctionSchema` form).
- [ ] The `--minimal-prompt` path still works (now Claude + `MINIMAL_SYSTEM_PROMPT`
  vs Claude + full native-tool prompt); `MINIMAL_SYSTEM_PROMPT` is unchanged.
- [ ] `EvalOutput`/`AgentEvalOutput` no longer carry a `base_url` field describing
  a llama.cpp endpoint; they record the **model id** under test instead (rename to
  `model` / reuse `model_label`). `compare.py` / `eval/agent/compare.py` are
  otherwise unchanged (they diff `aggregates`, not the endpoint).
- [ ] The Opus judges, synthetic learner, `eval/scoring/*`, `eval/fixtures/*`, and
  the disk cache are unchanged.
- [ ] `pytest` passes. A new **opt-in live smoke** (gated on `ANTHROPIC_API_KEY`,
  like the existing `test_agent_*_smoke.py`) runs one fixture through the
  Claude-under-test path and asserts a native `log_turn` tool call comes back and
  `score_turn` yields a `TurnResult`. Offline: a unit test that the caller adapts
  a fabricated Anthropic response (text block + `tool_use` block) into the correct
  `(text, parsed_log_turn)` — no network.
- [ ] ruff + mypy clean.

### Non-Goals

- **No judge / synthetic-learner model bump.** They stay on `claude-opus-4-7`
  (still an active model). Bumping to current Opus would require invalidating the
  disk caches (`JUDGE_SYSTEM_VERSION` / `LEARNER_SYSTEM_VERSION` don't include the
  model id) — its own change. Deferred (Open Question 3).
- **No scoring / rubric changes.** The 7-dimension fixture scoring and the 5-dim
  session judge are unchanged; this slice changes *who is scored*, not *how*.
- **No deletion of the vestigial text-form tool-call parsing** in
  `eval/scoring/turn.py`. It's harmless and keeps `parse_tool_calls` able to score
  raw-text output; flagged as future cleanup (it's now used only by eval, since
  the runtime handler that shared it was removed in spec 001).
- **No CI gating.** Eval makes real (billed) Anthropic calls; it stays a
  manual/opt-in tool, as today. No new blocking CI step.
- **No fixture regeneration** and no new personas.

### Open Questions

1. **Under-test model default.** `claude-sonnet-4-6` (the runtime model) —
   recommended so eval tests production. Configurable via `--model`. Confirm.
2. **Native tool-calling under test** (Key Decision 1). Recommended: mirror the
   runtime's native `log_turn` path (`tool_mode="native"`, `tool_use` block).
   Alternative: keep text-form emission (`tool_mode="text"`) and the regex parser.
   Native is the faithful choice; confirm.
3. **Judge/learner model bump** — defer (Non-Goal) vs bump-with-cache-invalidation
   now. Lean defer.

---

## How

### Approach

**Shared Anthropic tool + caller.** Add `LOG_TURN_ANTHROPIC_TOOL` to
`hable_ya/tools/schema.py` — `{"name": "log_turn", "description": …,
"input_schema": {"type": "object", "properties": LOG_TURN_PROPERTIES, "required":
LOG_TURN_REQUIRED}}` — the Anthropic Messages-API tool shape, reusing the existing
constants. Introduce a small async helper (in `eval/` — e.g. `eval/agent_client.py`
or a function in `run_eval.py`) that wraps `anthropic.AsyncAnthropic().messages.create(
model, system, messages, tools=[LOG_TURN_ANTHROPIC_TOOL], max_tokens, thinking
disabled)` and returns `(spoken_text, parsed_log_turn_calls)` by collecting `text`
blocks and adapting each `tool_use` block to `{"name": b.name, "arguments": b.input}`
for `parse_tool_calls(text, api_tool_calls=[…])`. Both entrypoints call it.

**`eval/run_eval.py`.** Replace the `openai` client + `call_model` body with the
helper; system prompt = `MINIMAL_SYSTEM_PROMPT` (minimal) or
`render_system_prompt(fixture.system_params, band=…, tool_mode="native")` (full);
drop `--base-url`/`--no-thinking`, add `--model` (default `settings.llm_model_name`);
record the model id in `EvalOutput`.

**`eval/agent/run_agent_eval.py`.** Same swap in `_call_agent` (build Anthropic
`messages` from the transcript, tools + native parse); replace `llama_client` with
an `anthropic.AsyncAnthropic()`; drop `DEFAULT_BASE_URL`/`LLAMA_MODEL_ID`/
`--base-url`/`--no-thinking`; `--model-label` → `--model` recorded in
`AgentEvalOutput`. `_build_turn_record` already consumes `parse_tool_calls` output,
so it's unchanged. Update `_cost_preview` to include the under-test model's tokens
(Sonnet pricing) or note it.

**Untouched:** `opus_judge.py`, `judge_recasts.py`, `synthetic_learner.py`,
`eval/scoring/*`, `eval/fixtures/*`, `_cache.py`, both `compare.py`.

### Confidence

**Level:** Medium

**Rationale:** The mechanism is well-understood and proven — this is the same
Anthropic-SDK + native-`log_turn` shape spec 001 shipped for the runtime, and the
`{"name","arguments"}` adapter into `parse_tool_calls` is exactly what the runtime
handler already does. The judges/scoring/fixtures are confirmed decoupled. What
keeps it Medium: several call sites across two multi-arg CLIs, the `EvalOutput`
schema field change, the cost-preview update, and — critically — the under-test
path has **no existing offline test coverage** (the llama.cpp call sites were
never exercised by tests), so correctness rests on a new offline adapter test plus
a live smoke.

**Validate before proceeding:**
1. Confirm Open Questions 1–2 (model default + native tool-calling) — they shape
   the whole slice.
2. Run the new live smoke (`ANTHROPIC_API_KEY`) end to end on one fixture + one
   persona before calling it done — the real proof Claude emits a scorable
   `log_turn` under the eval prompt.

### Key Decisions

1. **Native tool-calling under test, mirroring the runtime.** The eval must
   measure what production does; the runtime emits `log_turn` as a native
   `tool_use` block (spec 001), so eval renders `tool_mode="native"` and reads the
   structured block. This retires the text-form regex path for eval (kept in the
   scorer as dead-but-harmless — Non-Goal).
2. **Default the under-test model to the runtime model** (`settings.llm_model_name`
   = `claude-sonnet-4-6`), configurable — eval tracks the deployed model.
3. **Reframe the comparator, don't rewrite it.** `compare.py` still diffs two
   `EvalOutput` JSONs; the meaningful axis is now minimal-prompt vs full-prompt (or
   model A vs model B), not Gemma-state-vs-state. Only help text / labels change.
4. **One Anthropic `log_turn` tool constant in `schema.py`.** Avoids eval
   re-deriving the tool shape; single source with the runtime's `FunctionSchema`.
5. **Keep judges/learner on `claude-opus-4-7`** (defer the bump + cache
   invalidation) to keep the slice focused on the under-test swap.

### Testing Approach

- **New offline unit test** (`tests/test_eval_agent_client.py` or similar): feed
  the caller/adapter a fabricated Anthropic `Message` (a `text` block + a
  `tool_use` block with `log_turn` input) via a mocked `AsyncAnthropic`; assert it
  returns the spoken text and a parsed `log_turn` with the right args — proves the
  block→`parse_tool_calls` adaptation without network.
- **Existing eval tests carry over:** `test_scoring.py` (both `parse_tool_calls`
  paths), `test_agent_{cache,learner,judge_prompts,aggregates,personas}.py`,
  `test_validate_fixtures.py` — all offline/mocked, unaffected by the under-test
  swap.
- **New live smoke** (`tests/test_eval_claude_smoke.py`, `skipif` on
  `ANTHROPIC_API_KEY`, matching the existing smokes): run one standard fixture
  through the Claude-under-test path; assert a native `log_turn` tool call is
  returned and `score_turn` produces a `TurnResult` (schema-level assertions, not
  exact scores).
- **Gates:** `ruff check hable_ya api eval/agent tests scripts`; `mypy hable_ya api
  eval/agent`; `pytest`.
- **Manual:** a small `python -m eval.run_eval --model claude-sonnet-4-6 --output …`
  run over one category to eyeball recast quality + `log_turn` emission rate vs the
  ~80% Gemma baseline (the emission-rate question from the runtime memory).
