# Decision Record: Cloud LLM — Claude via Native Tool-Calling

| Field | Value |
|---|---|
| id | 001 |
| status | implemented |
| created | 2026-07-05 |
| spec | [spec.md](./spec.md) |

---

## Context

`habla` is the cloud-API fork of `hable-ya`; the on-device runtime was ported
in verbatim first (commit `6451c4d`). This slice swaps the LLM at the model
boundary — fine-tuned Gemma over llama.cpp (`OpenAILLMService`, emitting
`log_turn(...)` as plain text that a custom processor regex-parsed and stripped)
→ **Claude Sonnet 4.6** via Pipecat's `AnthropicLLMService` with **native
structured tool-calling**.

Two things shaped the implementation beyond the spec:

1. **Reading the installed `pipecat-ai 0.0.108` source** settled the spec's one
   Medium-confidence unknown and refined the approach. Confirmed: the Anthropic
   service streams `LLMTextFrame` to TTS *and* runs the tool call in the same
   turn (text is never suppressed — `services/anthropic/llm.py:1174-1181`);
   native tool calls surface via `register_function(name, handler)` whose
   `result_callback` writes the `tool_result` back into context; and, notably,
   `tool_choice` is stored on the context but **not forwarded to the API** in
   0.0.108.

2. **A live spike gated the rewrite** (spec Confidence: Medium). It PASSED on all
   five checks, including a two-turn test proving the answered `tool_use` keeps
   the next request from 400-ing — so the single-call design held and the
   documented two-call fallback was not needed.

## Decision

The runtime LLM is **Claude Sonnet 4.6** via `AnthropicLLMService`, with thinking
disabled (voice latency). `log_turn` is a **native tool** registered on the
per-session `LLMContext`; the model calls it while also speaking, in one turn.
Consumption is a **`register_function` handler** (`make_log_turn_handler`) that
dispatches the observation and answers the call with
`FunctionCallResultProperties(run_llm=False)` — fire-and-forget, no second
inference. `tool_choice` is left unset, so Anthropic's default `auto` applies
(the model both speaks and calls). The old text-parsing `HableYaToolHandler` is
removed; a tiny `LogTurnEmissionObserver` counts turns with no call for the
`sink.missing` emission metric. The shared runtime prompt gains a `tool_mode`
flag so the runtime renders a native "call the tool" instruction while the
fine-tune/eval workstreams keep the byte-identical plain-text contract.

---

## Alternatives Considered

### How the pipeline consumes the native tool call

**Option A — `register_function` handler (chosen).** Register a `log_turn`
handler on the LLM service; it dispatches the observation and calls
`result_callback(..., run_llm=False)`.
- Pros: one wiring point; receives already-parsed `arguments`; the
  `result_callback` writes the required `tool_result` into context, so the next
  turn can't 400; idiomatic Pipecat.
- Cons: the service is a shared singleton, so the per-session closure must be
  re-registered each session.

**Option B — keep a downstream `FrameProcessor`** watching
`FunctionCallInProgressFrame` for the side-effect, plus a trivial catch-all
handler just to answer the protocol.
- Pros: mirrors the old handler's position in the pipeline.
- Cons: two wiring points; still needs a registered handler to satisfy the
  `tool_result` requirement (an unanswered `tool_use` 400s the next turn), so it
  strictly adds moving parts over A.

**Chosen: A.** B's only advantage evaporated once native tool-calling removed the
text-stripping premise. The one downside (re-registration) is safe under
single-tenant.

### `tool_choice` — auto vs forced

**Option A — leave unset / `auto` (chosen).**
- Pros: the model both speaks and calls the tool in one turn — exactly what the
  voice loop needs; it's Anthropic's default with tools present.
- Cons: emission is best-effort (consistent with the existing degrade-gracefully
  contract).

**Option B — force `tool_choice: {type: "tool", name: "log_turn"}`.**
- Pros: guarantees emission.
- Cons: **forcing suppresses the spoken reply** — Claude emits only the tool
  call, fatal for a speech turn. Also moot in pipecat 0.0.108, which doesn't
  forward `tool_choice` to the API at all (would need a `settings.extra` hack).

**Chosen: A.** Reliability comes from native tool-calling + a strong prompt, not
forcing. This corrects the spec's loose "force emission with tool_choice" wording
(#002).

### The `sink.missing` emission metric

**Option A — a turn-boundary observer (chosen).** `LogTurnEmissionObserver`
watches `LLMFullResponseStartFrame` / `FunctionCallInProgressFrame(log_turn)` /
`LLMFullResponseEndFrame`; increments `missing` on turns that ended with no call.
Frame ordering is deterministic (`run_function_calls` is awaited before the end
frame — `llm_service.py:629,643`), so no race.
- Pros: preserves the emission-rate metric (the whole point of `missing` per the
  project's "log_turn emits ~80%" memory); race-free.
- Cons: reintroduces one small (counting-only) processor.

**Option B — drop no-call-turn accounting**, let `missing` count only malformed
calls (from the handler).
- Cons: loses the emission-rate signal — can't measure whether Claude beats the
  ~80% Gemma baseline.

**Chosen: A.** The two paths are mutually exclusive per turn (a turn either had a
call → handler, or didn't → observer), so `missing` stays single-counted.

### Model tier

Sonnet 4.6 (chosen) over Haiku 4.5 (cheaper/faster, revisit after live latency)
and Opus (wrong tier for real-time voice). Rationale: best recast/assessment
judgment at a real-time-viable latency/cost. Confirmed live: natural recasts
(*"ayer fuiste a la tienda"*) and correct per-turn CEFR banding.

### Runtime prompt vs shared source

`tool_mode` flag on `render_system_prompt` (chosen) over forking `render.py` or
mutating the shared prompt. Keeps `render.py` the single source of truth; the
native change is confined to the runtime path, so eval/fine-tune byte-identity
tests stay green.

---

## Tradeoffs

- **Per-turn token cost** replaces free local inference (product shift owned by
  #015; billing/telemetry by #014).
- **Shared-singleton re-registration** of the handler each session is safe only
  under single-tenant (one active session). Documented; `unregister_function` is
  deliberately avoided (raises on double-call).
- **Pinned pipecat** — 0.0.108 always sends the `interleaved-thinking-2025-05-14`
  beta header even with thinking disabled (`llm.py:528`). Harmless (confirmed
  live), but the version is pinned so it can't silently change.
- **Latency lever is thinking-disabled, not `effort`** — `AnthropicLLMService`
  doesn't expose `effort` in 0.0.108. Deferred to #013 (would go via
  `settings.extra`).
- **STT/TTS still local** — a GPU is still required for whisper until #007.
- **`temperature=0.7` fixed** (not exposed as config) — matches the prior
  conversational warmth; only one of temperature/top_p is set (Claude 4+ rejects
  both).

---

### Spec Divergence

The implementation matched the spec's intent; three points diverged in mechanism
and are recorded here.

| Spec Said | What Was Built | Reason |
|---|---|---|
| #002: "force emission with `tool_choice`" | `tool_choice` left unset (Anthropic default `auto`) | Forcing suppresses the spoken reply; pipecat 0.0.108 doesn't forward `tool_choice` anyway. |
| #003: "rework the tool handler to consume native function-call frames" | Removed `HableYaToolHandler`; consumption is a `register_function` handler + a counting-only `LogTurnEmissionObserver` | `register_function` is the idiomatic path and also writes the required `tool_result`; a frame-parsing processor would strictly add moving parts. |
| #005: disable thinking **and** low effort | Thinking disabled; effort not set | `effort` isn't a native `AnthropicLLMService` param in 0.0.108. |
| (implicit) `anthropic` available to the runtime | Installed via `uv sync --extra eval`; `pyproject` not edited | Promoting `anthropic` to core deps is #010's job; this slice stayed code-only. |

---

## Spec Gaps Exposed

- **`tool_choice` is not forwarded to the API in pipecat 0.0.108.** If a future
  slice needs forcing — e.g. the spec's two-call fallback, where an async
  assessment call *would* force `log_turn` — it must inject Anthropic-style
  `tool_choice` via `settings.extra`. Worth noting in that follow-up spec.
- **`effort` is not exposed by `AnthropicLLMService`.** #013 (latency
  re-benchmark) may want it via `settings.extra`.
- **`anthropic` still lives in the `eval` extra, not core deps.** #010 must
  promote it (the runtime now hard-depends on it).
- **Step 8 (live mic session) is human-run.** The agent can't drive a microphone,
  so the live emission-rate-vs-80%-baseline and end-to-end latency measurements
  are deferred to a human run. The spike validated the LLM integration
  end-to-end at the frame level in the meantime.

---

## Test Evidence

Offline gates (spacy `es_core_news_sm` installed as the documented setup step):

```
$ uv run pytest -q
241 passed, 52 skipped, 9 warnings in 13.55s

$ uv run ruff check hable_ya api tests scripts
All checks passed!

$ uv run mypy hable_ya api
Success: no issues found in 45 source files
```

Live spike (`scripts/spike_anthropic_tools.py`, Claude Sonnet 4.6, two turns):

```
--- spike results ---
(a) turn1 spoke Spanish   : True  -> '¡Hola, Ana! Qué bien, ayer fuiste a la tienda. ¿Qué compraste allí?'
(b) handler fired w/ args : True  -> keys=['L1_used', 'cefr_band', 'errors', 'fluency_signal', 'learner_utterance']
(c) result frame emitted  : True
(d) turn2 ok, no API error: True  -> '¡Perfecto, Ana! Compraste cosas muy importantes. ¿Tienes una tienda favorita cerca de tu casa?'
(e) thinking-disabled run : True (both turns completed with the interleaved-thinking beta header always on)

PASS — green light for the rewrite
```

The turn-1 tool call logged the L1 interference + tense error with `cefr_band:
A1`, `L1_used: True`; turn-2 logged `errors: []`, `cefr_band: A2`,
`L1_used: False` — and turn 2 completing with no API error is the proof that the
turn-1 `tool_use` was correctly answered by a `tool_result`.
