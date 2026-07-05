# Spec: Cloud LLM — Claude via Native Tool-Calling

| Field | Value |
|---|---|
| id | 001 |
| status | draft |
| created | 2026-07-05 |
| covers roadmap | #001, #002, #003, #004, #005, #006 (bundle) |

---

## Why

`habla` is the cloud-API fork of `hable-ya`. In `hable-ya` the runtime LLM is a
**fine-tuned Gemma 4 E4B** served over a llama.cpp OpenAI-compatible endpoint,
reached through Pipecat's `OpenAILLMService` (`hable_ya/pipeline/services.py`).
The fine-tune is the product: one model acts as conversational partner *and*
pedagogical assessor, emitting a plain-text `log_turn(...)` call inline with its
Spanish reply, which `HableYaToolHandler` parses out of the text stream and
strips before TTS (`hable_ya/pipeline/processors/tool_handler.py`). The tool
schema in `hable_ya/tools/schema.py` is documentation only — it is **not**
registered with the model (`api/routes/session.py`: *"HABLE_YA_TOOLS is not
injected into the LLM"*).

Moving to Claude changes the contract at the model boundary. There is no
fine-tune; the pedagogy must be reproduced with prompting + **native structured
tool-calling**. This slice swaps the LLM service, registers the tool, reworks
the handler to consume native tool-call blocks instead of regex-parsing text,
and strips the Gemma/llama.cpp-specific plumbing. It is the highest-risk part of
the migration and the thing everything else depends on, so it lands first.

### Prerequisite (roadmap #000, out of this spec)

The `habla` repo is currently empty. This spec assumes the `hable-ya` runtime —
`hable_ya/`, `api/`, `eval/scoring/`, the Pipecat pipeline, the Postgres/AGE
learner stack — is **ported in verbatim as the starting point**, then modified
by the changes below. Porting the codebase is a separate mechanical step (see
Open Question #1: copy wholesale vs. cherry-pick). The acceptance criteria are
written against that ported baseline.

### Consumer Impact

- **End user (learner):** No surface change. They speak Spanish, hear a
  band-appropriate Spanish reply. What changes is the model producing it and the
  fact that their audio/transcript now leaves the device (see roadmap #015 for
  the privacy posture; out of this spec).
- **Project owner:** Gains a runtime backed by a frontier model with **native**
  tool-calling. The `log_turn` observation arrives as a validated structured
  block rather than best-effort text, and emission reliability should rise well
  above the fine-tuned Gemma's ~80% (`sink.missing` becomes the way to confirm
  that on live sessions). Per-turn token cost is now non-zero.
- **Downstream:** The learner model (ingest, profile, leveling), themes, and the
  eval harness consume `log_turn` observations unchanged — the *shape* of a
  `TurnObservation` is preserved; only its provenance (native block vs. parsed
  text) changes. The eval re-baseline (#012) and STT/TTS swaps (#007/#008) are
  separate slices.

### Roadmap Fit

Bundles six planned items because splitting them lands non-functional
intermediates (a Claude service that can't emit `log_turn`, a handler with no
native blocks to consume, a config with dead llama.cpp knobs):

- **#001** Claude LLM via Pipecat `AnthropicLLMService`.
- **#002** Register `HABLE_YA_TOOLS`; emit `log_turn` via native tool-calling.
- **#003** Rework the tool handler to consume native function-call blocks.
- **#004** Move the `log_turn` emission instruction into the tool definition.
- **#005** Config: Anthropic model id + key; drop llama.cpp knobs + thinking hack.
- **#006** Replace the llama.cpp warmup ping with an API health check.

Dependencies: upstream is the #000 port. Downstream unblocked by this: #007/#008
(STT/TTS swaps), #012 (eval re-baseline), #013 (latency re-benchmark).

---

## What

### Provider decisions (settled here, confirm in review)

- **Provider:** Anthropic Claude, via Pipecat's Anthropic LLM service (the repo
  already depends on `anthropic` for eval). Model id is exact-string
  `claude-sonnet-4-6` — **recommended default** for a real-time voice tutor: it
  reproduces the recast + assessment judgment far better than Haiku while being
  materially faster and cheaper than Opus, which is the wrong tier for a
  latency-critical speech loop. `claude-haiku-4-5` is the fallback to A/B if
  latency or cost dominate; Opus is explicitly not the target. (Model ids per
  the `claude-api` reference; see Open Question #2.)
- **Latency posture:** disable extended thinking (`thinking: {type: "disabled"}`)
  and run low effort. This is the direct analog of the Gemma
  `chat_template_kwargs.enable_thinking=false` hack we're deleting — a voice turn
  must not stall on a reasoning pass.

### Acceptance Criteria

With the ported baseline + a valid `ANTHROPIC_API_KEY`:

- [ ] `hable_ya/pipeline/services.py` constructs an **Anthropic** Pipecat LLM
  service in place of `OpenAILLMService`. The `base_url`, `api_key="not-needed"`,
  and the `extra_body.chat_template_kwargs.enable_thinking` block are gone.
- [ ] `hable_ya/config.py` exposes `anthropic_api_key` and an Anthropic
  `llm_model_name` defaulting to `claude-sonnet-4-6`. `llama_cpp_url` is removed;
  every reference to it (services, warmup, tests) is updated or deleted.
- [ ] `HABLE_YA_TOOLS` (the `log_turn` schema in `hable_ya/tools/schema.py`) is
  **registered with the LLM context / passed to the Anthropic service** so the
  model calls it natively. The comment in `api/routes/session.py` stating the
  tools are not injected is removed, and the tool is actually wired in.
- [ ] `tool_choice` is `auto` (the model may both speak and call `log_turn` in
  one turn), **not** a forced single tool — forcing suppresses the spoken reply
  (see Key Decision 3). The system prompt instructs the model to call `log_turn`
  exactly once after every reply.
- [ ] During a live session, when Claude emits a native `log_turn` tool call, the
  reworked `HableYaToolHandler`:
    1. Reads the tool call from the native function-call frame(s) Pipecat
       surfaces — **not** by regex-parsing buffered `LLMTextFrame` text. The
       existing `eval/scoring/turn.py::parse_tool_calls` already accepts an
       `api_tool_calls` argument for exactly this path; reuse it (pass the
       structured call, `text=None`/unused).
    2. Normalizes via `normalize_runtime_log_turn_args`, validates, and dispatches
       a `TurnObservation` to the sink + ingest — the existing downstream path is
       unchanged.
    3. Increments `sink.missing` when a turn produces no `log_turn` call, and
       `sink.band_missing` when `cefr_band` is absent — same counters as today.
    4. Lets the spoken text reach TTS. Because the tool call is now a separate
       native block, there is no tool-call syntax to strip from the spoken text.
- [ ] The spoken Spanish reply is never contaminated by tool-call syntax
  (trivially true once emission is native, but assert it).
- [ ] The system prompt no longer instructs the model to emit a plain-text
  `log_turn(...)` surface form. That instruction moves into the tool
  `description` / the tool registration; the human-readable band rubric the tool
  description already builds (`_build_cefr_band_description`) is preserved.
- [ ] Warmup (`services.py::warmup_llm`) no longer pings a llama.cpp endpoint in a
  retry loop. It either does a single cheap Anthropic health check (e.g. a 1-token
  `messages.create`) or is removed and the readiness gate in
  `api/routes/session.py` adjusted accordingly.
- [ ] `settings.llm_max_tokens` is re-tuned so both the spoken reply and the
  `log_turn` tool call fit (150 was sized for Gemma's text-only reply; native
  tool args add tokens — bump modestly and note the value chosen).
- [ ] `pytest` passes, including the reworked handler tests (see Testing Approach).
  Tests that asserted text-form `log_turn(...)` parsing are updated to the native
  path.

### Non-Goals

- **No STT/TTS change.** faster-whisper and Piper stay in this slice (#007/#008
  swap them). The app may still need a GPU for whisper until then — accepted.
- **No eval re-baseline** (#012). The eval harness still runs; validating that
  Claude + prompt reproduces recast/`log_turn` fidelity is its own slice.
- **No prompt-content rewrite.** The band rubric, register guidance, forbidden
  phrases, cold-start block, and theme rendering carry over as-is. Only the
  `log_turn` *emission instruction* moves (into the tool). Tuning the prompt for
  Claude's instruction-following is a follow-up if #012 shows drift.
- **No fine-tuning.** There is no fine-tune in `habla`. All behavior is prompt +
  tool-schema + model choice.
- **No deployment/deps cleanup** (#009–#011). The llama.cpp compose service and
  the `finetune/` package removal are separate. This spec makes the code stop
  *using* llama.cpp; it doesn't delete the container or dependencies.
- **No cost/rate-limit hardening** (#014). tenacity retries carry over; explicit
  backoff and token-cost telemetry are their own slice.
- **No decoupled two-call assessment.** Kept single-call (see Key Decision 3);
  the async-assessment alternative is documented as the fallback, not built.

### Open Questions

1. **Port wholesale vs. cherry-pick?** Copy the entire `hable-ya` tree into
   `habla` (fastest; carries `finetune/`, `cuda_bootstrap`, benchmarks as
   dead-for-now code that #011 later removes) vs. import only the runtime +
   eval-scoring + learner packages. **Recommend wholesale** — it keeps git
   provenance and lets #009–#011 do the removal deliberately. Resolve with owner.
2. **`claude-sonnet-4-6` vs `claude-haiku-4-5` default.** Recommend Sonnet 4.6
   for assessment quality; Haiku 4.5 if a latency/cost measurement (part of #013)
   says otherwise. This is a 1-line config default — resolve after the first live
   latency read, or ship Sonnet and revisit.
3. **Exact Pipecat Anthropic binding.** The service class name, how tools/
   `tool_choice` are threaded through `LLMContext`, and how tool-call frames
   surface must be verified against the installed `pipecat-ai` version — this spec
   fixes the *design*, the decision record captures the exact API. Whether
   text + tool_use co-emit cleanly through Pipecat's Anthropic streaming is the
   load-bearing thing to confirm during implementation (Key Decision 3).

---

## How

### Approach

**LLM service (#001, #005, #006).** In `hable_ya/pipeline/services.py`, replace
the `OpenAILLMService(base_url=…, api_key="not-needed", …, extra_body=…)`
construction with Pipecat's Anthropic service, `model=settings.llm_model_name`
(`claude-sonnet-4-6`), `api_key=settings.anthropic_api_key`, thinking disabled /
low effort, `max_completion_tokens` re-tuned. Delete the `enable_thinking`
`extra_body`. Rework `warmup_llm` into a single Anthropic health check (or drop
it and simplify the readiness gate). `config.py`: add `anthropic_api_key`, point
`llm_model_name` at the Claude id, remove `llama_cpp_url`.

**Tool registration (#002, #004).** Pass `HABLE_YA_TOOLS` into the Anthropic
service / `LLMContext` at session build (`api/routes/session.py`,
`hable_ya/pipeline/runner.py`). Set `tool_choice: auto`. Remove the "tools not
injected" comment. In the prompt renderer, delete the plain-text
`log_turn(...)`-emission instruction; keep the CEFR band rubric where the tool
`description` already renders it (`schema.py::_build_cefr_band_description`).

**Tool handler (#003).** Rewrite `HableYaToolHandler` to consume native
tool-call frames. The buffering-until-`LLMFullResponseEndFrame` scaffold is
replaced by handling Pipecat's function-call frames; on each `log_turn` call,
run it through `parse_tool_calls(..., api_tool_calls=<call>)` (the branch already
built for structured calls in `eval/scoring/turn.py`), then the existing
`normalize_runtime_log_turn_args` → validate → `TurnObservation` →
`sink.append` / `ingest.ingest` path, with the same `missing` / `band_missing` /
`ingest_failed` counters. Spoken text flows to TTS untouched — no
`strip_tool_calls` needed.

The pipeline order in `runner.py` (`… → llm → tool_handler → tts → …`) stays;
what changes is that `tool_handler` now taps native tool-call frames instead of
sitting in the text stream to strip syntax.

### Confidence

**Level:** Medium.

**Rationale:** The downstream half is low-risk — `TurnObservation`, the sink, the
normalizer, the band rubric, and `parse_tool_calls`'s `api_tool_calls` path all
already exist and are exercised by eval fixtures; this slice re-points them at a
native source. The prompt content carries over. The real uncertainty is the
**Pipecat ⇄ Anthropic native tool-calling integration in a streaming voice
loop**: whether a single Claude turn cleanly co-emits spoken text *and* a
`log_turn` tool_use block through Pipecat's Anthropic service, and how those
frames are surfaced to a downstream processor. That determines whether the
single-call design (Key Decision 3) holds or we fall back to the async two-call
approach. It needs a spike against the installed `pipecat-ai` before the handler
rewrite is finalized.

**Validate before proceeding:**

1. Spike: one live Claude turn through the Pipecat Anthropic service with
   `HABLE_YA_TOOLS` registered and `tool_choice: auto` — confirm text + a
   `log_turn` tool_use arrive together and are separable into TTS text vs. a
   tool-call frame. If not, escalate to Key Decision 3's fallback.
2. Resolve Open Question #1 (port strategy) so the baseline exists.

### Key Decisions

1. **Bundle #001–#006; the port (#000) is a prerequisite, not part of this
   spec.** The six items are one coherent change at the model boundary;
   splitting them strands non-functional stubs.
2. **Claude Sonnet 4.6 default, not Opus.** Real-time voice is latency-critical;
   Opus is the wrong tier. Sonnet 4.6 balances the recast/assessment judgment
   against speed/cost; Haiku 4.5 is the cheaper A/B candidate. Disable thinking +
   low effort for the same latency reason (the Claude analog of dropping the
   Gemma `enable_thinking=false` hack).
3. **Single-call, `tool_choice: auto` — not forced.** The turn must produce both
   a spoken Spanish reply *and* the `log_turn` observation. Forcing
   (`tool_choice: {type: "tool", name: "log_turn"}`) makes Claude emit **only**
   the tool call with no conversational text — fatal for a speech turn. So
   emission is requested via `auto` + a strong prompt instruction, and
   reliability comes from native tool-calling + frontier instruction-following
   rather than from forcing. This corrects roadmap #002's loose "force emission
   with tool_choice" wording.
   **Fallback (documented, not built):** if `auto` emission proves unreliable or
   the co-emission adds latency, decouple into two calls — a tools-free
   conversational call for speech, plus an async, off-critical-path assessment
   call (optionally Haiku) that *is* `tool_choice`-forced to emit `log_turn` at
   ~100%. Cleaner reliability at the cost of a second call and a slight
   assessment lag; deferred to a follow-up spec if the spike demands it.
4. **Preserve graceful degradation.** Even with native tool-calling, a turn may
   omit `log_turn`. The `sink.missing` / `band_missing` counters stay — every
   downstream consumer was already built to tolerate a missing observation, and
   that contract is unchanged. `sink.missing` on live sessions is how we measure
   whether native emission actually beats the ~80% Gemma baseline.
5. **Reuse `parse_tool_calls`'s `api_tool_calls` path, don't fork.** The scoring
   module already normalizes structured tool calls; the handler should feed
   native blocks through it rather than growing a second parser.

### Testing Approach

The ported `tests/` suite covers the sink, normalizer, and scoring. This slice
re-points the handler tests at the native path.

**Unit tests to update / write:**

- `tests/test_tool_handler.py` (rewrite): drive the handler with a fabricated
  Pipecat frame stream carrying a **native** `log_turn` tool call (well-formed
  4/5-key args) plus a spoken-text frame. Assert (a) `sink.append` called once
  with a `TurnObservation` whose fields match, (b) the spoken text reaches TTS
  unchanged, (c) `sink.missing` not incremented. Add cases: no tool call →
  `missing` increments and text still flows; malformed args → dropped, `missing`
  increments; missing `cefr_band` → `band_missing` increments. Delete/replace the
  old text-form `log_turn(...)` / `[TOOL_CALL: …]` parsing assertions.
- `tests/test_tools.py`: `HABLE_YA_TOOLS` still validates a well-formed call and
  rejects missing `learner_utterance` / non-list `errors` / bad `fluency_signal`
  / non-bool `L1_used`. Add: the tool is in the shape the Anthropic service
  expects (the registration adapter, if any, round-trips the schema).
- `tests/test_prompts.py`: assert the rendered system prompt **no longer**
  contains the plain-text `log_turn(...)` emission instruction, while the band
  rubric, register guidance, forbidden phrases, and cold-start block are intact.
- Config: a test that `llama_cpp_url` is gone and `anthropic_api_key` /
  `llm_model_name=claude-sonnet-4-6` are present.

**Manual validation (human-run, out of pytest):**

- With `ANTHROPIC_API_KEY` set and STT/TTS running, hold a ~2-minute Spanish
  conversation. Confirm: (a) band-appropriate spoken Spanish, (b) one
  `runtime_turns.jsonl` line per turn that emitted `log_turn`, well-formed with
  the canonical keys incl. `cefr_band`, (c) TTS never speaks tool syntax, (d)
  `sink.missing` roughly matches turns with no observation — and record the live
  emission rate to compare against the ~80% Gemma baseline.
- Eyeball end-to-end latency (the `UserBotLatencyObserver` from `runner.py` still
  works) to sanity-check the Sonnet-4.6 + thinking-disabled choice before #013
  benchmarks it properly.
