# Decision Record: Cloud round-trip latency re-benchmark & turn-taking re-tune

| Field | Value |
|---|---|
| id | 013 |
| status | implemented |
| created | 2026-07-06 |
| spec | [spec.md](./spec.md) |

---

## Context

The turn-taking defaults (`smart_turn_stop_secs=4.0`, `vad_stop_secs=0.5`) were
on-device carry-overs, tuned when STT/LLM/TTS ran locally. The cloud fork added
a per-turn network hop that was never measured, so the re-tune had no evidence
base. This slice built the measurement tooling, ran it against the live APIs,
and set the defaults from the result.

The measurement reshaped the decision. The owner-confirmed target was p50
end-to-end ≤ 1.5s / p95 ≤ 2.5s (user-stop → first bot audio). The benchmark
(`scripts/benchmark_latency.py`, 20 iterations, `docs/specs/013-cloud-latency/latency.json`)
found the **network stages alone already exceed it**, before any endpointing
delay is added:

| stage | p50 ms | p95 ms | mean ms |
|---|---|---|---|
| STT (`gpt-4o-transcribe`) | 711 | 1229 | 826 |
| LLM TTFT (`claude-sonnet-4-6`) | 1179 | 1581 | 1152 |
| TTS TTFB (`sonic-3`) | 161 | 204 | 169 |
| **summed network floor** | **2051** | **3014** | — |

Perceived latency = endpointing wait + this floor. Since the floor is ~2.05s p50
(dominated by LLM TTFT and STT), the p50≤1.5s target is **unreachable by
endpointing tuning** — even instant endpointing leaves ~2.05s. The re-tune's job
narrowed accordingly: don't add to the floor, and reclaim the excessive
on-device endpointing ceiling.

## Decision

Built three durable artifacts and made one evidence-gated config change:

1. **`scripts/benchmark_latency.py`** — repeatable per-stage cloud latency
   harness (replacing the on-device one deleted in #011), driving the live
   `Services` for STT/LLM/TTS TTFB at p50/p95/mean.
2. **`PerStageLatencyObserver`** — live per-stage TTFB breakdown under
   `latency_debug`, from Pipecat's `MetricsFrame`s, alongside the existing
   end-to-end number.
3. **Re-tune:** `smart_turn_stop_secs` **4.0 → 3.0**; `vad_stop_secs` **kept at
   0.5** (evidence-backed no-op). SmartTurn's `stop_secs` is the *maximum*
   silence before force-ending an utterance the model is still uncertain about,
   so it only bites on trailing/uncertain turns — exactly what a learner
   pausing to think produces. Trimming 4.0→3.0 reclaims 1s on that tail while
   keeping a generous learner-pause cushion; VAD stop stays put because lowering
   it risks cutting a learner off mid-sentence for little gain on the
   already-floor-bound common path.

The measurement's headline — the target is infeasible on the network legs alone
— is recorded in ARCHITECTURE Key Constraints and motivates a follow-up
(faster STT/LLM or streaming-partial STT) that #013's Non-Goals explicitly
exclude.

---

## Alternatives Considered

### How aggressively to cut `smart_turn_stop_secs`

**Option A — 4.0 → 3.0 (chosen).** Conservative 1s trim.
- Pros: removes the on-device-era excess; measurable win on the uncertain-turn
  tail; keeps a 3s cushion for learners to formulate — consistent with the
  product's pedagogical priority (recast-based, learner-paced). Defensible
  without a large live A/B.
- Cons: leaves latency on the table if learners rarely need the full pause.

**Option B — 4.0 → ~2.0 (aggressive).** Chase responsiveness harder.
- Pros: reclaims more of the endpointing tail.
- Cons: real risk of cutting off mid-thought pauses — worse for language
  learners than for native speakers — and it still doesn't approach the p50
  target (network floor dominates), so the risk buys little. Would need a live
  learner study to justify, which we don't have.

**Option C — leave 4.0 (no-op).** 
- Pros: safest against premature cut-off.
- Cons: keeps an unjustified on-device artifact; the roadmap explicitly flagged
  it for re-tune; 4s of dead air on an uncertain turn (on top of ~2s network) is
  a poor experience.

**Chosen:** A. The measurement says endpointing can't hit the target, so the
right move is a conservative trim of the clear on-device excess, not an
aggressive gamble that trades learner experience for latency the network floor
negates anyway.

### `vad_stop_secs` — change or keep

**Chosen: keep 0.5** (the spec explicitly allowed an evidence-backed no-op).
0.5s is already reasonable; it applies on every turn including the
confident-complete path where latency is already floor-bound, so shaving it
saves little, while lowering it makes the agent more likely to interrupt a
learner's natural pause. No evidence justified changing it.

---

## Tradeoffs

- **The re-tune is modest by design.** It reclaims ~1s on uncertain turns and
  removes an on-device artifact, but does not — and provably cannot — bring
  perceived latency under the target. That ceiling is the cloud network floor,
  which this feature measures but (per Non-Goals) does not optimize.
- **The chosen `smart_turn_stop_secs=3.0` is validated by reasoning + the param
  semantics, not yet by a live learner study.** The spec's third validation
  step (drive a `voice_client.py` session with `latency_debug=on` to confirm no
  premature cut-off) is a human-run check; the conservative value keeps risk low
  pending it.
- **The benchmark is direct-`Services`, not the full WS pipeline.** It isolates
  network TTFT cleanly (what the tuning needs) but does not itself measure the
  endpointing behavior — that is the live-session check. Deliberate split (spec
  Key Decision).
- **Numbers are a single run on one network path.** p50/p95 will vary by region,
  time of day, and provider load; the harness exists precisely so they can be
  re-measured rather than trusted as fixed.

---

### Spec Divergence

The implementation matched the spec's approach. All acceptance criteria are met;
the config re-tune landed as an evidence-backed change (not the "already
optimal" no-op the spec allowed as an alternative outcome). One structural
refinement beyond the written steps:

| Spec Said | What Was Built | Reason |
|---|---|---|
| Wire the observer inside `build_pipeline_task` | Extracted a `build_observers(settings)` helper, wired there | Testable without constructing a `PipelineTask` (which doesn't cleanly expose its observers); cleaner single responsibility |
| Benchmark "drives the three `Services` directly" incl. TTS | STT direct + LLM raw-SDK stream, but **TTS via a persistent capture pipeline** | Streaming Cartesia's `run_tts()` doesn't return audio — it pushes frames downstream over a websocket — so a direct call can't observe TTFB; the capture-pipeline pattern (from `smoke_stt_tts.py`) is the only faithful way |

---

## Spec Gaps Exposed

- **The latency target is infeasible by this feature's levers.** The spec set a
  p50≤1.5s / p95≤2.5s budget assuming endpointing tuning could approach it; the
  measurement shows the network floor (~2.05s p50) exceeds it regardless. This
  is not a spec error so much as a discovery the spec anticipated (Q1 noted
  "subject to what the measured network floor permits"). It surfaces a genuine
  follow-up roadmap candidate: **latency optimization** (a faster STT model,
  streaming-partial STT to overlap transcription with speech, or a
  faster/Haiku-class LLM for first-token) — all #013 Non-Goals. Worth weighing
  against the pedagogical value of the current models.
- **`smart_turn_stop_secs=3.0` wants a live learner-pause validation** before it
  can be called settled; captured as a tradeoff, not a blocker.

---

## Test Evidence

Offline suite (no live API in CI) — new `tests/test_latency.py` (stats,
stage-mapping, observer capture/dedup/ignore) + extended `tests/test_runner.py`
(observer wiring):

```
$ uv run pytest -q
274 passed, 52 skipped, 9 warnings in 14.15s

$ uv run ruff check hable_ya/ api/ eval/agent/ tests/ scripts/
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 56 source files
```

A bug the tests caught during development: the per-stage observer first deduped
`MetricsFrame`s on Python's `id()`, but short-lived frames get their address
reused, so the LLM/TTS frames collided with the STT frame's id and were dropped
(only STT logged). Fixed by deduping on Pipecat's process-unique `frame.id`.
Without the test this would have silently under-reported stages in production.

Live run (human-run, real APIs) — `scripts/benchmark_latency.py`, 20 iterations,
full output in `docs/specs/013-cloud-latency/latency.json`:

```
stage           n      p50      p95     mean
stt            20      711     1229      826
llm            20     1179     1581     1152
tts            20      161      204      169
--------------------------------------------
end_to_end            2051     3014
(end_to_end = summed per-stage p50/p95; excludes endpointing delay)
```

Outstanding (human-run): a `voice_client.py` + `latency_debug` session to
confirm the per-stage log lines render and `smart_turn_stop_secs=3.0` does not
cut off natural learner pauses.
