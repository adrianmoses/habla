# Spec: Response Latency (Time to First Word)

| Field | Value |
|---|---|
| id | 024 |
| status | approved |
| created | 2026-07-24 |

---

## Why <!-- required -->

Response latency — how long the learner takes to *start* answering after the
tutor finishes a question or statement — is a fluency signal none of the
existing instrumentation captures. The `analiza` package measures pauses,
articulation rate, and fillers *within* a solo recording, but it has no
interlocutor and therefore no "question ended" anchor; the runtime's latency
tooling (#013) measures the *bot's* responsiveness (user-stopped → bot-started
via `UserBotLatencyObserver`, plus the STT/LLM/TTS TTFB split), never the
learner's. Yet the live Pipecat pipeline already carries both events needed for
the inverse measurement: `BotStoppedSpeakingFrame` (tutor turn ends) and
`VADUserStartedSpeakingFrame` (learner speech onset, with VAD back-correction
data). This spec adds the missing observer and persists the measurement
per turn, so hesitation-before-responding becomes a trackable trend alongside
the per-turn `fluency_signal` the model already logs.

### Consumer Impact <!-- required -->

- **The learner (project owner)** gets an objective, per-turn responsiveness
  number — the conversational analogue of `analiza`'s leading-silence metric —
  to watch trend downward as automaticity improves toward DELE B2.
- **The learner model / read API (#019, #020)**: each measurement lands on the
  `turns` row (`raw_extra`), so future progress surfaces can aggregate it
  (avg response latency per session) without re-instrumenting the pipeline.
- **The JSONL dev sink** (`runtime_turns.jsonl`, `/dev/observations`) carries
  the same value for immediate inspection without a DB query.

### Roadmap Fit <!-- required -->

Builds directly on #013's observer wiring (`build_observers`,
`PerStageLatencyObserver` pattern) and #016's per-session service isolation
(the observer and the `log_turn` handler are both per-session, so pairing them
is race-free by construction). Feeds #019/#020: the value is persisted where
the read API already looks, but surfacing it in HTTP payloads / UI is
explicitly deferred to those features. Independent of #014/#021/#022.

---

## What <!-- required -->

### Acceptance Criteria <!-- required -->

- [ ] During a live session, each learner turn that begins after a completed
  tutor turn produces a response-latency measurement: seconds from the tutor's
  audio ending to the learner's voice onset (VAD-corrected).
- [ ] The measurement is attached to that same turn's `log_turn` observation:
  it appears as `response_latency_ms` (int) in `TurnObservation.extra`, in the
  JSONL sink line, and in the `turns.raw_extra` JSONB column.
- [ ] Turns with no valid anchor produce **no** measurement (absent key, not
  0): the first learner turn of a session (no prior tutor speech), barge-ins
  (learner starts while the tutor is still speaking), and turns whose
  `log_turn` never fired.
- [ ] A multi-part tutor reply (bot resumes speaking before the learner
  responds) measures from the *final* bot stop, not the first.
- [ ] The measurement is logged under `hable_ya.latency`
  (`response_latency_ms=<n>`) so `latency_debug` sessions show it inline with
  the #013 numbers.
- [ ] Offline unit tests cover the observer state machine and the
  handler/ingest plumbing; the full suite, ruff, and mypy stay green.

### Non-Goals <!-- required -->

- **No first-word semantics.** VAD onset fires on any vocalization, including
  fillers ("ehh…"). v1 measures time-to-first-*sound*; distinguishing filler
  onset from lexical onset (cross-referencing the STT transcript) is future
  work — the gap between the two is itself a hesitation signal `analiza`
  already tracks via fillers.
- **No `analiza` integration.** The offline pipeline has no interlocutor
  anchor; nothing changes there.
- **No read-API / frontend surfacing.** `turns.raw_extra` is the contract;
  aggregation into `/api/learner/*` payloads or UI belongs to #019 follow-ups
  / #020.
- **No schema migration.** `turns.raw_extra JSONB NOT NULL DEFAULT '{}'`
  already exists (migration `bd55d203ae25`) — it has simply never been
  written. This spec starts writing it; no new column.
- **No pedagogical use.** The value is not fed into the system prompt,
  leveling, or placement. Observation only.

### Open Questions <!-- optional -->

Resolved at spec time (owner pre-approved implementation in-session; defaults
chosen per the recommendation):

1. **Always-on or gated on `latency_debug`?** → **Always-on.** This is a
   learner metric, not a debug metric; the observer is O(1) per frame and the
   #013 debug observers stay gated. Only the *logging* rides the existing
   `hable_ya.latency` logger.
2. **Persist to a dedicated column or `raw_extra`?** → **`raw_extra`.** Zero
   migration, and the read shape is still queryable
   (`(raw_extra->>'response_latency_ms')::int`). Promote to a column if/when
   #019 aggregates it server-side.
3. **Which clock anchors "tutor stopped"?** → **Server-side observation time
   of `BotStoppedSpeakingFrame`** (`time.time()` when observed — the frame
   carries no timestamp field). Known skew: the client buffers some audio, so
   true playback end lags the server-side stop by the buffer depth. Accepted
   for v1; the number is consistent turn-over-turn, which is what a trend
   needs. (Same posture as Pipecat's own `UserBotLatencyObserver`, which
   stamps `BotStartedSpeakingFrame` at observation time.)

---

## How <!-- required -->

### Approach <!-- required -->

**1. New observer** — `hable_ya/pipeline/processors/response_latency.py`,
class `ResponseLatencyObserver(BaseObserver)`, mirroring
`PerStageLatencyObserver`'s conventions (frame-id dedup ring, `records` deque
for tests, `hable_ya.latency` logger). State machine over downstream frames:

- `VADUserStartedSpeakingFrame`: set `_user_speaking = True`. If an anchor is
  armed: `latency = (frame.timestamp - frame.start_secs) - anchor` — the
  frame's `timestamp` is when VAD *confirmed* speech, `start_secs` is the
  confirmation window, so the difference is true onset (the same
  back-correction Pipecat applies to the stop event at
  `user_bot_latency_observer.py:250`). Discard negatives; record, log, set
  `pending_ms` (overwrite), disarm the anchor.
- `VADUserStoppedSpeakingFrame`: `_user_speaking = False`.
- `BotStoppedSpeakingFrame`: arm the anchor with `time.time()` **iff
  `not _user_speaking`** — on a barge-in the bot's stop is caused by the
  learner already talking, and a mid-turn learner pause+resume must not
  measure against it.
- `BotStartedSpeakingFrame`: disarm the anchor — a resumed multi-part tutor
  reply re-arms on its own (final) stop.

The anchor is one-shot: only the first learner onset after a clean tutor stop
measures. `pending_ms: int | None` is a public consume-once slot: `pop()`
returns and clears it. Overwrite-on-measure + pop-on-log means a turn whose
`log_turn` never fired cannot leak its value onto a later turn (the next
measurement overwrites before the next `log_turn` reads).

**2. Wiring** — the observer must be reachable by both the pipeline task and
the `log_turn` handler, so it is built in the session route
(`api/routes/session.py`), per session:

- `make_log_turn_handler(sink, session_id, ingest=ingest, latency=observer)` —
  new optional keyword. On a validated `log_turn`, `pop()` the pending value
  into `TurnObservation.extra["response_latency_ms"]`. Timing is safe by
  pipeline ordering: the value is measured at the learner's speech onset,
  which strictly precedes that turn's STT → LLM → `log_turn` dispatch.
- `build_pipeline_task(..., extra_observers=[observer])` → `build_observers`
  gains the parameter and always includes them; the `latency_debug` gate keeps
  applying only to the #013 observers. (`build_observers` returns the list
  instead of `None` when extras are present.)

**3. Persistence** — `TurnIngestService._insert_turn` adds `raw_extra` to the
INSERT, serialized from `obs.extra` via `json.dumps` (asyncpg passes JSONB as
text). This closes the latent gap that `TurnObservation.extra` was silently
dropped on the DB path (it already flows to JSONL via `asdict`). Empty dict
keeps writing `'{}'`, matching the column default — no behavior change for
existing rows or tests.

Files touched: `response_latency.py` (new), `runner.py`,
`log_turn_handler.py`, `session.py`, `ingest.py`, plus tests. No config, no
deps, no migration.

### Confidence <!-- required -->

**Level:** High

**Rationale:** Every mechanism is an established pattern in this codebase: the
observer mirrors `PerStageLatencyObserver` (#013), the handler closure already
takes optional collaborators (`ingest=`), per-session isolation (#016) makes
the observer↔handler pairing race-free, and the target column exists unused.
The frame semantics were verified against the installed Pipecat source
(`VADUserStartedSpeakingFrame.timestamp/start_secs` exist;
`BotStoppedSpeakingFrame` is timestamp-less, hence observation-time stamping,
same as Pipecat's own observer). Residual uncertainty is confined to the
client-audio-buffer skew on the anchor (accepted, Open Question 3) and
real-conversation edge sequences (barge-in, multi-part replies), which the
state machine handles explicitly and unit tests pin.

### Key Decisions <!-- optional -->

1. **Measure live, not offline.** The question-end anchor only exists in the
   Pipecat frame stream; `analiza` inputs cannot recover it (its leading-
   silence metric is file-relative). Any offline approach would require
   recording both conversation sides — far more machinery for a worse signal.
2. **Consume-once handoff instead of turn-id correlation.** The observer and
   handler share a session; pipeline ordering guarantees measure-before-log
   within a turn. A turn-id join (via `TurnTrackingObserver`) would be more
   general but adds coupling for no current consumer.
3. **`_user_speaking` guard over `InterruptionFrame` handling.** Both detect
   barge-ins; tracking VAD start/stop is self-contained and also covers the
   pause-resume-mid-turn case that interruption frames don't describe.

### Testing Approach <!-- required -->

Offline pytest (no DB, no network), following `tests/` conventions for #013's
observer tests — synthetic `FramePushed` events driven through
`on_push_frame`:

1. **Happy path:** bot stop → user onset ⇒ one record with VAD
   back-correction applied (`timestamp - start_secs - anchor`); logged;
   `pending_ms` set.
2. **First turn:** user onset with no prior bot stop ⇒ no record.
3. **Barge-in:** user start → bot stop → user stop ⇒ anchor never arms; the
   learner's next onset (before the tutor speaks again) measures nothing.
4. **Multi-part reply:** bot stop → bot start → bot stop → user onset ⇒
   measures from the second stop only, one record.
5. **One-shot anchor:** two user onsets after one bot stop ⇒ one record.
6. **Consume-once:** `pop()` returns the value then `None`; a second
   measurement overwrites an unconsumed first.
7. **Handler integration:** `make_log_turn_handler(..., latency=observer)`
   with a pending value ⇒ `TurnObservation.extra["response_latency_ms"]` set
   and slot cleared; with no pending value ⇒ key absent.
8. **Ingest (DB suite, skips without Postgres):** `ingest()` of an
   observation with `extra` ⇒ `turns.raw_extra` round-trips it; empty `extra`
   ⇒ `'{}'`.
9. **Gates:** full pytest suite, scoped ruff + mypy clean.

Live validation (deferred, same class as #016–#023: full boot fail-fasts
without the three cloud-API keys): a keyed session confirming plausible
`response_latency_ms` values in `runtime_turns.jsonl` — flagged for the owner
in the decision record.
