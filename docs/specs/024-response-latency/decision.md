# Decision Record: Response Latency (Time to First Word)

| Field | Value |
|---|---|
| id | 024 |
| status | implemented |
| created | 2026-07-24 |
| spec | [spec.md](./spec.md) |

---

## Context <!-- required -->

Direct user ask: "measure the time to first word — when I first respond to a
question or statement." Feasibility exploration confirmed the metric belongs
in the live runtime, not `analiza` (no interlocutor anchor in a solo
recording), and that the Pipecat frame stream already carries both events —
the spec and implementation followed in one session, with the owner
pre-approving implementation, so the spec's Open Questions were resolved at
spec time with the recommended defaults rather than a review round-trip.

Two facts discovered during exploration shaped the design and were baked into
the spec before any code was written: `BotStoppedSpeakingFrame` carries **no
timestamp** (so the anchor is stamped at observation time — the same posture
Pipecat's own `UserBotLatencyObserver` takes on the bot-started side), and
`turns.raw_extra JSONB` existed since migration `bd55d203ae25` but was **never
written** by `TurnIngestService._insert_turn` — `TurnObservation.extra` was
silently dropped on the DB path while flowing fine to JSONL. This spec's
persistence need closed that latent gap.

## Decision <!-- required -->

Measure learner response latency live, per session, with a new
`ResponseLatencyObserver` (`hable_ya/pipeline/processors/response_latency.py`)
attached to every pipeline task, and persist it per turn through the existing
`log_turn` path.

The observer is a small state machine over deduped frames: a **one-shot
anchor** arms at `BotStoppedSpeakingFrame` (stamped `time.time()`) **only when
the learner is not already speaking** (barge-in guard, tracked via VAD
start/stop frames), disarms on `BotStartedSpeakingFrame` (so a multi-part
tutor reply measures from its final stop), and fires on the next
`VADUserStartedSpeakingFrame` as `(frame.timestamp − frame.start_secs) −
anchor` — the same VAD back-correction Pipecat applies on the stop side.
Negative values are discarded. The measurement lands in a consume-once
`pending_ms` slot; the per-session `log_turn` handler (`latency=` keyword)
pops it into `TurnObservation.extra["response_latency_ms"]`, which now
persists to both the JSONL sink (already worked) and `turns.raw_extra`
(ingest INSERT extended). Wiring is always-on via a new `extra_observers`
parameter on `build_pipeline_task`/`build_observers`; the `latency_debug`
gate still applies only to the #013 diagnostics.

## Alternatives Considered <!-- required -->

### Where to measure

**Option A: Live, in the Pipecat frame stream (chosen)**
- Pros: both anchors already exist as timestamped events; per-session
  isolation (#016) makes observer↔handler pairing race-free; ~100 lines.
- Cons: server-side stop stamp lags true client playback end by the client's
  audio buffer depth.

**Option B: Offline, extending `analiza`**
- Pros: one metrics home alongside the other fluency metrics.
- Cons: structurally impossible with current inputs — a solo recording has no
  "question ended" anchor; would require recording both conversation sides
  and aligning them. Spec Non-Goal.

**Chosen:** A. The anchor only exists live.

### Turn association: consume-once slot vs turn-id correlation

**Option A: Consume-once `pending_ms` slot (chosen)**
- Pros: zero coupling; correctness follows from pipeline ordering (onset
  strictly precedes that turn's STT → LLM → `log_turn` dispatch);
  overwrite-on-measure + pop-on-log means a turn with no `log_turn` cannot
  leak its value onto a later turn.
- Cons: implicit contract with the frame ordering rather than an explicit id
  join.

**Option B: Turn-id join via Pipecat's `TurnTrackingObserver`**
- Pros: explicit correlation, generalizes to more per-turn metrics.
- Cons: adds a turn-tracking dependency and id plumbing through the handler
  for no current consumer.

**Chosen:** A — simplest thing that is provably correct under the ordering.

### Barge-in detection: `_user_speaking` guard vs `InterruptionFrame`

**Option A: Track VAD start/stop into a `_user_speaking` flag (chosen)**
- Pros: self-contained; also covers the learner pause-resume-mid-turn
  sequence after a barge-in, which interruption frames don't describe.
- Cons: one more piece of internal state.

**Option B: Listen for `InterruptionFrame`**
- Pros: semantically explicit.
- Cons: only covers the interruption moment, not the subsequent stale-anchor
  window; couples to `allow_interruptions` mechanics.

**Chosen:** A.

### Persistence: `raw_extra` vs dedicated column (spec OQ2)

Resolved in the spec: `raw_extra` — zero migration, queryable via
`(raw_extra->>'response_latency_ms')::int`; promote to a column if #019
aggregates server-side. Only one approach was on the table for the *write*
mechanics: `_insert_turn` gains the column with `json.dumps(obs.extra)`
(asyncpg passes JSONB as text), preserving `'{}'` for empty — byte-compatible
with the column default, so existing rows/tests are unaffected.

## Tradeoffs <!-- required -->

- **Anchor accuracy vs machinery.** The server-side `BotStoppedSpeakingFrame`
  stamp leads true client playback end by the client buffer depth, so
  absolute values read slightly high-side-consistent. Accepted: the number is
  consistent turn-over-turn, which is what a trend needs; fixing it would
  require client-side playback telemetry.
- **First-sound, not first-word.** VAD onset includes fillers ("ehh…"). v1
  deliberately measures time-to-first-vocalization; lexical-onset via STT
  cross-reference is future work (spec Non-Goal), and the filler gap is
  itself tracked by `analiza`.
- **Turns without measurement carry no key** (first turn of a session,
  barge-ins, negative corrections) rather than a 0 — consumers must treat
  absence as "not measured," which is the honest semantics but requires a
  null-aware aggregation later.
- **Always-on** adds one O(1)-per-frame observer to every session —
  negligible, and avoids a config knob nobody would turn off.

### Spec Divergence <!-- optional -->

**None.** The implementation matches the spec exactly — all five approach
points (observer state machine, consume-once handoff, `extra_observers`
wiring, handler keyword, `raw_extra` INSERT) landed as written, and every
Testing Approach case exists as a named test.

| Spec Said | What Was Built | Reason |
|---|---|---|
| — | — | no divergences |

## Spec Gaps Exposed <!-- optional -->

- **`turns.raw_extra` was dead schema** (also noted in the spec, confirmed in
  implementation): `TurnObservation.extra` flowed to JSONL but was dropped on
  the DB path since the learner-model migration. Now fixed; other historical
  rows all hold the default `'{}'`, so no backfill question arises.
- **Aggregation is unspecified by design**: surfacing `response_latency_ms`
  (e.g. per-session average / trend) in `/api/learner/*` and the UI is
  deferred to #019 follow-ups / #020 — those specs should decide whether to
  aggregate in SQL over `raw_extra` or promote a column.
- **Live validation deferred** (same class as #016–#023): a full boot
  fail-fasts without the three cloud-API keys, so the observer was validated
  offline only. Owner check: run a keyed session and confirm plausible
  `response_latency_ms` values appear in `runtime_turns.jsonl` /
  `turns.raw_extra`.

## Test Evidence <!-- required -->

New + adjacent tests (observer state machine, handler integration, runner
wiring, DB round-trip — DB up):

```
tests/test_response_latency.py::TestObserver::test_happy_path_with_vad_back_correction PASSED
tests/test_response_latency.py::TestObserver::test_no_anchor_on_first_turn PASSED
tests/test_response_latency.py::TestObserver::test_barge_in_never_arms PASSED
tests/test_response_latency.py::TestObserver::test_multi_part_reply_measures_from_final_stop PASSED
tests/test_response_latency.py::TestObserver::test_anchor_is_one_shot PASSED
tests/test_response_latency.py::TestObserver::test_negative_latency_discarded PASSED
tests/test_response_latency.py::TestObserver::test_dedups_same_frame PASSED
tests/test_response_latency.py::TestObserver::test_ignores_unrelated_frames PASSED
tests/test_response_latency.py::TestObserver::test_pop_is_consume_once PASSED
tests/test_response_latency.py::TestObserver::test_new_measurement_overwrites_unconsumed PASSED
tests/test_response_latency.py::test_handler_consumes_pending_into_extra PASSED
tests/test_response_latency.py::test_handler_no_pending_leaves_extra_empty PASSED
tests/test_response_latency.py::test_handler_without_observer_unchanged PASSED
tests/test_runner.py::test_build_observers_off_by_default PASSED
tests/test_runner.py::test_build_observers_includes_per_stage_when_debug PASSED
tests/test_runner.py::test_build_observers_extras_always_included PASSED
tests/test_runner.py::test_build_observers_extras_alongside_debug PASSED
tests/test_log_turn_ingestion.py::test_ingest_persists_extra_to_raw_extra PASSED
tests/test_log_turn_ingestion.py::test_ingest_empty_extra_writes_empty_object PASSED
======================== 32 passed, 9 warnings in 3.26s ========================
```

Full suite with Postgres up (zero skips), plus CI-scoped lint/type gates:

```
$ uv run pytest tests/ -q
469 passed, 9 warnings in 16.67s

$ uv run ruff check hable_ya/ api/ eval/agent/ tests/ scripts/
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 63 source files
```
