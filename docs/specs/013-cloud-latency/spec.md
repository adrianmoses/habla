# Spec: Cloud round-trip latency re-benchmark & turn-taking re-tune

| Field | Value |
|---|---|
| id | 013 |
| status | implemented |
| created | 2026-07-06 |

---

## Why

The turn-taking parameters `smart_turn_stop_secs` (4.0s) and `vad_stop_secs`
(0.5s) were tuned for the **on-device** hable-ya, where STT (faster-whisper
CUDA), the LLM (Gemma over llama.cpp), and TTS (Piper) all ran locally with no
network hop. The cloud fork replaced all three with managed APIs (#001/#007), so
every turn now pays a network round-trip to OpenAI (STT), Anthropic (LLM
time-to-first-token), and Cartesia (TTS time-to-first-byte) that did not exist
when those defaults were chosen.

Perceived response latency in a voice agent is the sum of two budgets:

```
perceived latency = endpointing delay (vad_stop_secs / smart_turn_stop_secs)
                  +  STT + LLM TTFT + TTS TTFB   ← the newly-added network hop
```

The endpointing delay is a deliberate wait to be *sure* the learner finished
speaking (cutting them off mid-thought is worse than a small delay). The cloud
hop inflates the second term, so the total may now exceed the responsiveness a
learner tolerates in conversation. This feature **measures** the cloud per-stage
latency and **re-tunes** the endpointing defaults to rebalance the budget —
spending less on the endpointing wait, where the measurement justifies it,
without regressing into premature turn-cutting.

Two durable artifacts fall out: a repeatable latency benchmark harness (the
on-device `benchmark_latency.py` was deleted in #011 and never replaced), and
per-stage latency visibility in the live runtime (today `latency_debug` logs
only an end-to-end number, not the STT/LLM/TTS split needed to diagnose *which*
hop dominates).

### Consumer Impact

- **End user (learner):** Directly benefits from a more responsive conversation.
  The endpointing re-tune shortens the dead air between "learner stops talking"
  and "agent starts replying" to the extent the measured network latency allows,
  keeping the exchange conversational rather than walkie-talkie.
- **Developer / operator:** Gets (a) `scripts/benchmark_latency.py` to quantify
  the current cloud latency profile on demand (e.g. after a model or provider
  change), and (b) a per-stage `latency_debug` breakdown in production logs to
  localize a regression to STT vs LLM vs TTS instead of guessing.

### Roadmap Fit

Depends on the model boundary being fully cloud (#001, #007) and CPU-only
(#009) — all landed. It is the natural first hardening item now that the
migration series (#001–#015) is closed: the pipeline is functionally correct but
its turn-taking was never re-tuned for the new latency shape. Independent of
#014 (API resilience & cost) — that item addresses failure/cost, this one
addresses responsiveness; they share no code and can land in either order.

---

## What

### Acceptance Criteria

- [ ] `scripts/benchmark_latency.py` exists and, given the three provider keys,
      drives a representative corpus of Spanish turns through the cloud services
      and reports per-stage latency — STT, LLM TTFT, TTS TTFB — and a synthesized
      end-to-end figure, as p50 / p95 / mean over N iterations (N configurable,
      sensible default).
- [ ] The harness is deterministic in structure (fixed prompt corpus, fixed
      iteration count) and prints a human-readable table; an optional
      `--output <file.json>` writes the raw numbers for the decision record.
- [ ] `latency_debug` in the live runtime emits a **per-stage** breakdown (STT
      TTFB, LLM TTFB/TTFT, TTS TTFB) in addition to the existing end-to-end
      `end_to_end_ms`, sourced from Pipecat's `MetricsFrame` (`enable_metrics`
      is already on).
- [ ] `smart_turn_stop_secs` and `vad_stop_secs` defaults in `config.py` are set
      from the measured cloud latency profile, with the chosen values and their
      justification recorded (decision record + a note in ARCHITECTURE Key
      Constraints). If measurement shows the existing values are already optimal,
      that is a valid outcome — but it must be an evidence-backed decision, not a
      no-op by omission.
- [ ] The cloud latency profile (measured p50/p95 per stage) and the on-device
      reference it is compared against are documented, with the comparison's
      status (live cloud numbers vs. historical on-device reference) stated
      honestly.
- [ ] Offline unit tests cover the harness's aggregation (percentile/mean) logic
      and the per-stage metrics-capture path (fed synthetic `MetricsFrame`s), so
      CI does not depend on live API calls.
- [ ] CI gates stay green: `pytest`, CI-scoped `ruff` (`hable_ya/ api/
      eval/agent/ tests/ scripts/`) and CI-scoped `mypy` (`hable_ya/ api/
      eval/agent/`). New runtime code under `hable_ya/` must be mypy-clean.

### Non-Goals

- **Not** reducing the APIs' intrinsic latency — the providers' TTFT/TTFB are a
  given. This feature measures and rebalances around them; it does not try to
  make Anthropic/OpenAI/Cartesia faster.
- **Not** a provider/model swap for speed (e.g. moving to a faster STT model or a
  Haiku-class LLM). Any such change is a separate decision informed by, but not
  part of, this benchmark.
- **Not** a latency *optimization* feature — no streaming-partial STT,
  speculative LLM prefill, or TTS pre-warming. Those are larger items the
  measurement may motivate later.
- **Not** a load / concurrency benchmark (that was the separate, never-ported
  `benchmark_concurrency.py`; concurrency/cost is #014's territory).
- **Not** a closed-loop auto-tuner — the re-tune is a one-time, evidence-backed
  default change, not an adaptive controller.

### Open Questions

- **Q1 — target latency budget. RESOLVED (owner-confirmed 2026-07-06):** target
  is **p50 end-to-end ≤ 1.5s and p95 ≤ 2.5s** (user-stop → first bot audio),
  subject to what the measured network floor actually permits — if the cloud hop
  alone exceeds this, the re-tune claws back what it can and the gap is
  documented rather than forced.
- **Q2 — measurement surface: direct-services vs full WS pipeline.** *Proposed:*
  the benchmark drives the three `Services` directly (isolates network TTFT,
  deterministic, no synthetic-speech-with-pauses needed); the endpointing re-tune
  is validated separately through the live `latency_debug` path on a real
  `voice_client.py` session. Direct-services is sufficient because `stop_secs`
  governs endpointing *before* the network hop — the number we need to re-tune
  against is the downstream latency, which direct-services measures cleanly.
- **Q3 — on-device baseline provenance.** The GPU path was deleted in #009, so
  "vs local" cannot be a live A/B. *Resolution (deferred):* treat the on-device
  numbers as a documented historical reference (hable-ya benchmarks / project
  memory), and frame the comparison as directional, not a reproducible
  regression gate. Accepted as a known limitation, not a blocker.

---

## How

### Approach

Three deliverables — a benchmark harness, per-stage runtime instrumentation, and
the config re-tune — plus documentation.

1. **Benchmark harness — `scripts/benchmark_latency.py`.** Reuses the
   direct-`Services` pattern already established in `scripts/smoke_stt_tts.py`
   (`load_services(settings)` is available). For each of a fixed corpus of short
   Spanish learner utterances (audio synthesized once via Cartesia, or a small
   bundled WAV set), run N iterations measuring:
   - **STT latency:** submit audio → transcript returned.
   - **LLM TTFT:** send the transcript through the context → first token frame.
   - **TTS TTFB:** send reply text → first `TTSAudioRawFrame`.
   Collect samples, compute p50/p95/mean per stage + a summed end-to-end
   estimate, print a table, and optionally dump JSON. Requires the three keys;
   fails fast if any is missing (mirrors `smoke_stt_tts.py`).

2. **Per-stage runtime instrumentation (`hable_ya/pipeline/runner.py`).** Add a
   small `BaseObserver` (or metrics processor) that, when `settings.latency_debug`
   is set, consumes `MetricsFrame`s (already emitted because
   `PipelineParams(enable_metrics=True)`), extracts `TTFBMetricsData` per
   processor name (STT/LLM/TTS), and logs the split under the existing
   `hable_ya.latency` logger alongside the current `UserBotLatencyObserver`
   end-to-end line. No behavior change when `latency_debug` is off.

3. **Re-tune (`hable_ya/config.py`).** After running the harness against live
   APIs (validation step), set `smart_turn_stop_secs` / `vad_stop_secs` defaults
   from the evidence and the Q1 budget. The 4.0s `smart_turn_stop_secs` in
   particular is an on-device carry-over and the prime re-tune candidate. Record
   the before/after and rationale.

4. **Docs.** Record the measured cloud profile + on-device reference in the
   decision record; add a one-line pointer to the numbers and the new defaults in
   ARCHITECTURE Key Constraints (which already flags "#013" as the owner of this
   measurement). Fix the stale `scripts/voice_client.py` docstring
   ("Run against a live `uvicorn api.main:app` with **llama.cpp** up") left over
   from the on-device era — a small migration-debt cleanup adjacent to this work.

### Confidence

**Level:** Medium

**Rationale:** The mechanics are well-understood — Pipecat already emits the
metrics frames (`enable_metrics=True`), `load_services` gives direct service
access, and `smoke_stt_tts.py` / `voice_client.py` are working driving patterns
to build on. What is genuinely uncertain is the *data*: the actual cloud p50/p95
is unknown until measured against live APIs, and the re-tune is a judgment call
that depends on those numbers plus an owner-confirmed latency target (Q1). The
"vs local" comparison is also not reproducible (Q3). So the harness and
instrumentation are High-confidence to build; the *tuning decision* they feed is
Medium and must be evidence-gated.

**Validate before proceeding:**
- Run `scripts/benchmark_latency.py` against the live APIs to obtain real
  per-stage p50/p95 before touching `config.py` defaults. The measured numbers
  are the input to the re-tune — committing new `stop_secs` values without them
  would be guessing.
- Confirm the Q1 latency budget (target p50/p95) with the owner.
- Sanity-check the re-tuned `stop_secs` on a live `voice_client.py` session with
  `latency_debug=on` — verify the shorter endpointing wait does not cut off
  natural mid-utterance pauses (barge-in / premature-turn regression).

### Key Decisions

- **Measure via direct `Services`, validate the re-tune via the live WS
  pipeline.** Isolates the network-latency measurement (what the tuning needs)
  from the endpointing behavior (what the tuning affects), rather than trying to
  measure both through one noisy synthetic-speech WS run. Trade-off: two surfaces
  instead of one, but each is simpler and more trustworthy.
- **Evidence-gate the config change.** The spec deliberately does not pre-commit
  specific `stop_secs` values; they are an output of the live measurement, set
  during implementation and justified in the decision record. This keeps the
  spec honest — the numbers cannot be known in advance.
- **Reuse Pipecat metrics rather than hand-rolling timers.** Per-stage TTFB is
  already computed by Pipecat and surfaced as `MetricsFrame`; observing it is
  less code and stays correct as services change, versus wrapping each service in
  bespoke timing.

### Testing Approach

Per OVERVIEW's suite (pytest, `asyncio_mode=auto`, `testpaths=["tests"]`), with
live API calls kept out of CI:

- **Unit — aggregation:** feed the harness's percentile/mean helper a known
  sample vector, assert p50/p95/mean. Pure function, no API.
- **Unit — metrics capture:** construct the per-stage observer, feed it synthetic
  `MetricsFrame`s carrying `TTFBMetricsData` for STT/LLM/TTS processor names, and
  assert it records/logs the right per-stage values; feed a non-metrics frame and
  assert it is ignored. No API.
- **Unit — pipeline wiring:** assert `build_pipeline_task(..., latency_debug=True)`
  attaches the per-stage observer and that `latency_debug=False` leaves runtime
  behavior unchanged (regression guard on the existing path).
- **Live (human-run, like prior spec smokes):** execute
  `scripts/benchmark_latency.py` against real APIs; capture the p50/p95 table
  into the decision record. Then a `voice_client.py` + `latency_debug` session to
  confirm the re-tuned endpointing feels responsive without premature cut-off.
- **Regression gates:** `pytest`, CI-scoped `ruff` and `mypy` green; new
  `hable_ya/` code is mypy-clean (scripts/ is ruff- but not mypy-scoped in CI).
