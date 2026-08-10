# Spec: analiza progress-over-time reporting

| Field | Value |
|---|---|
| id | 034 |
| status | approved |
| created | 2026-08-09 |
| approved | 2026-08-09 |

---

## Why

`analiza` produces a rich per-session artifact and no way to read across
sessions. Every run writes a note, a CSV row, and raw JSON; nothing answers the
question the learner actually has after a month of practice — *am I getting
better, and at what?*

The CSV was built for this (`spec.md` §2F calls it "the 90-day trend line") but
carries only headline numbers. WPM rising from 58 to 75 is worth knowing;
it is not what a learner means by progress. What they mean is closer to *`por`
vs `para` stopped showing up*, and that signal lives in the per-session
`examiner.json` files, which nothing currently reads back.

**It is not readable today, and the reason is specific.** Running the examiner
twice over the *same* stored transcript — same `prompt_version`, same model —
produced:

| Same utterance | Run 1 | Run 2 |
|---|---|---|
| "me da miedo **para** pasar tiempo" | `gramatica` — "régimen preposicional incorrecto con 'miedo'" | `calco` — "'me da miedo para + infinitivo'" |
| "escuchar **a** español" | `calco` — "escuchar a + idioma (calco de 'listen to')" | `gramatica` — "régimen preposicional incorrecto con verbos" |
| gender agreement | "falta de concordancia de género en atributos" | "concordancia de género (adjetivos/sustantivos)" |

Two findings swapped `tipo` in opposite directions, and the finding that kept
its type still got a different `patron` string. `calcos_n` read 4 and then 3 on
identical audio.

Two consequences govern this spec:

1. **`patron` is free text, so there is no key to match a fault on across
   sessions.** Recurrence tracking by string comparison would find almost
   nothing recurring, which is indistinguishable from having fixed everything.
2. **`calcos_n` carries roughly ±1 of model noise on identical input.** A
   month-over-month move of 4 → 3 is not evidence of anything.

A progress feature built on the current artifacts would therefore narrate noise
with confidence. Making the findings addressable is the prerequisite, not a
refinement.

### Consumer Impact

The learner (single user, own practice recordings). Concretely, after ~10+
sessions they can ask for a report and get:

- which error patterns have stopped appearing, and when they last appeared
- which are still recurring after N sessions — the real "focus next" signal,
  currently re-derived from scratch each session with no memory of the last
- which deterministic metrics moved, and which moved less than their own noise
- an explicit refusal to report when there is not enough data, rather than a
  confident story fitted to five sessions

Second consumer: `analiza` itself. A stable `pattern_id` makes the examiner's
per-session `enfoque_proxima_sesion` answerable from history rather than from
one transcript.

### Roadmap Fit

Absorbs the `analiza stats` v1.1 slot (`docs/specs/analiza/spec.md` §6:
"plot WPM/formal-ratio/MTLD trends from the CSV; flag plateaus"). That slot
predates the v2 examiner and assumed the CSV was the whole story; this spec
supersedes it and says why.

**This is the first `analiza` row in `ROADMAP.md`.** The track has been specced
at `docs/specs/analiza/spec.md` and built without roadmap entries; `analiza`
is listed as System 4 in `OVERVIEW.md` but appears in no feature row.

Depends on the merged examiner_v2 work (PR #28): pattern-grouped `ErrorRow`,
`tipo`, `calcos_n`/`whisper_model` in the CSV, structured outputs. Nothing
depends on this spec.

Sequencing within the spec matters: the vocabulary (WS1) must land before
meaningful history accumulates, because every session recorded without a
`pattern_id` costs one backfill LLM call later.

---

## What

### Acceptance Criteria

- [x] Every `ErrorRow` carries a `pattern_id` drawn from a curated vocabulary,
      with `otro` as the escape hatch; `patron` remains as the human-readable
      label and is the only carrier of meaning when `pattern_id` is `otro`.
- [ ] Re-running the examiner twice over one stored transcript yields the same
      `pattern_id` set for the faults both runs found — the instability
      demonstrated above is confined to `patron` prose and `tipo`.
      *Partial: 8 of 12 ids in all three spike runs, and the residual is the
      10-pattern cap rather than the keying (§Validate). WS2 treats a capped
      session as truncated instead of assuming this criterion holds.*
- [x] A backfill command assigns `pattern_id` to every stored `examiner.json`
      that predates the vocabulary, in place, without re-transcribing.
- [x] `analiza progreso [--desde D] [--hasta D] [--ejercicio E]` reads
      `analiza-stats.csv` plus the `examiner.json` files in range and writes a
      progress note plus a machine-readable aggregation JSON.
- [x] The aggregation is computed by pure functions with no LLM involvement and
      is byte-identical across repeated runs over the same inputs.
- [x] Per-pattern recurrence reports, for each `pattern_id` seen: sessions
      appeared in, first seen, last seen, total instances, and a
      resolved/persistent classification.
- [x] Metric trends compare a first window against a last window rather than
      fitting a line, and each is reported with the session count behind it.
- [x] Sessions are segmented by `prompt_version` and `whisper_model`; a range
      spanning a boundary is reported per-segment and never as one trend.
- [x] Sessions whose `vad_transcript_gap_s` exceeds a configurable threshold are
      flagged low-confidence in both the aggregation and the note.
- [x] Below a configurable minimum session count the command declines to produce
      a narrative, states the count, and still writes the aggregation JSON.
- [x] `--no-llm` produces the aggregation and a numbers-only note.
- [x] The LLM pass receives the aggregation JSON, never raw transcripts, and
      returns a structured result validated against a pydantic model.
- [x] No LLM prose is written to `analiza-stats.csv`.
- [x] The progress prompt is a versioned asset with its version recorded in the
      output, following the examiner convention.

### Non-Goals

- **Re-scoring past sessions.** Historical `puntuaciones` stand as recorded.
  Backfill assigns `pattern_id` and touches nothing else.
- **Plots or charts.** The v1.1 roadmap line mentioned plotting; this produces
  markdown and JSON. Charting can read the aggregation later.
- **Cross-learner or cohort comparison.** Single user, consistent with the
  repo-wide single-tenant non-goal.
- **Pronunciation trends.** Still out of scope per `analiza` spec §5.
- **Runtime-agent integration.** No coupling to `hable_ya`, the learner
  database, or `/api/learner*`. `analiza` stays standalone (`OVERVIEW.md`
  System 4).
- **Automatic scheduling.** The command is run on demand.
- **Controlling for topic difficulty.** `tema` varies and affects every metric;
  this spec surfaces the confound in the note rather than modelling it.
- **A stable `tipo`.** The evidence above shows `tipo` is not reproducible.
  `pattern_id` becomes the tracking key; `tipo` stays a per-session label and
  is explicitly not trended.

### Open Questions

All resolved at approval (2026-08-09) toward the drafted proposals, except
where noted as deferred with a reason.

1. **Vocabulary size and authorship** — *resolved.* Seed by clustering the
   stored `examiner.json` corpus, then hand-edit to ~30–60 entries. A
   from-scratch list drafted against the DELE B2 rubric would miss this
   learner's actual faults; the corpus is small and already on disk. The
   hand-edit pass is not optional — clustering output is a starting point, and
   Key Decision 1 puts the granularity judgment in this file deliberately.
2. **Resolved threshold** — *resolved.* Configurable, default 3 consecutive
   absent sessions, and rendered as "absent for N sessions" rather than as a
   verdict. The report states the observation; calling a fault fixed is the
   learner's call.
3. **Minimum session count for a narrative** — *resolved* at 8, configurable.
   *Calibration explicitly deferred* until ≥10 sessions exist: at 2–3 sessions
   a week the number is a guess, and tuning it against a corpus of one would
   dress that guess as evidence.
4. **Window shape for metric trends** — *resolved.* Fixed first-N vs last-N with
   N=5, plus an explicit "insufficient sessions" state. Rejected first-third vs
   last-third because the comparison would silently change meaning as history
   grows, so two reports a month apart would not be comparing like with like.
5. **Should `pattern_id` also feed the CSV?** — *deferred*, with the reason
   standing: a variable-length list does not belong in a columnar contract the
   `analiza` spec describes as "numbers only, never LLM prose". Recurrence is
   computed from the `examiner.json` corpus, which is the durable artifact for
   exactly this kind of reprocessing (`analiza` spec §2C). Revisit only if
   opening every file per report becomes a real cost.
6. **Does the vocabulary change require `examiner_v3`?** — *resolved: yes.*
   Adding a required field changes the output contract, and the convention is
   one prompt version per contract. The comparability cost is one recorded v2
   session, which is the cheapest this bump will ever be — a further argument
   for sequencing WS1 first.

---

## How

### Approach

Three workstreams, sequenced. WS1 is a prerequisite for WS2's recurrence
tracking; WS3 depends on WS2's output.

**WS1 — Pattern vocabulary (`examiner_v3`).**

- `analiza/patrones_b2.py`, structured like `conectores_b2.py`: a frozen list of
  `Patron(id, etiqueta, tipo_habitual, ejemplos)` entries.
- `ErrorRow` gains `pattern_id: PatternId` (a `Literal` generated from the
  vocabulary, plus `otro`). `patron` stays, now the display label.
- `prompts/examiner_v3.md` + `schemas/output_schema_v3.json`, keeping v1/v2 per
  the versioning convention. The prompt instructs: pick the closest
  `pattern_id`; use `otro` only when nothing fits, and then make `patron`
  self-describing.
- Structured outputs enforce the enum server-side, exactly as `tipo` is enforced
  today, so an off-vocabulary id cannot reach the client.

**WS2 — Deterministic aggregation (`analiza/progreso.py`).**

Pure functions over plain data, no I/O and no LLM — the same posture as
`metrics.py`, and the unit-test target.

```
inputs   analiza-stats.csv rows + [examiner.json] in range
           │
           ├─ segment by (prompt_version, whisper_model)
           ├─ flag low-confidence sessions (vad_transcript_gap_s, duration)
           ├─ metric windows: first N vs last N per column
           └─ pattern recurrence: sessions/first/last/instances per pattern_id
           │
output   ProgresoStats  →  progreso.json
```

Segmentation is the load-bearing part: `errors_n` changed meaning at v2 (rows →
patterns) and `fillers_n` moves with `whisper_model`, so a range spanning either
boundary is reported per segment with the boundary named.

**As built (2026-08-10).** Five decisions the spec left to implementation:

- **Vocabulary versioning took the predicted CSV shape.** `vocab_version` is
  appended to `STATS_COLUMNS`, each `Patron` carries a `desde` version, and
  `ids_disponibles(version)` answers what a given session could have reported.
  A CSV written before the column is widened in place on the next append —
  `DictWriter` writes by fieldname and never reads the file, so appending a
  wider row to a narrower header would have silently misaligned every reader.
- **Absence is conclusive only when the session could have spoken.** Four
  disqualifiers, each a silence that means nothing: the session was never
  examined, it filled the examiner's pattern cap, the id did not yet exist at
  its vocabulary version, or its ids came from the backfill — which saw the
  finding prose and not the transcript, so a mis-key there manufactures a
  false absence as easily as a false presence. `estado` is therefore ternary:
  `persistente` / `ausente` / `no-concluyente`.
- **Recurrence spans segments; trends do not.** A `pattern_id` surviving a
  prompt bump is the entire point of the vocabulary, and the availability
  check above already covers the one boundary that genuinely breaks it.
- **Low confidence is a *ratio*** (`vad_transcript_gap_s / duration_s`,
  default 0.10), not an absolute second count: under an absolute threshold a
  20-minute session would have to be twice as broken as a 10-minute one to
  flag.
- **Not everything numeric is trended.** `errors_n`/`calcos_n` are capped and
  model-noisy (Key Decision 4), `pauses_n`/`connectors_unique` grow with
  session length — pauses becomes a derived `pauses_per_min` and connector
  variety is dropped — and `duration_s` describes the recording, not the
  speaker.

The read side lives in `analiza/historial.py` so `progreso.py` can stay pure
and its tests can run without a corpus.

**WS3 — Narrative pass (`progreso_v1.md`).**

`run_progreso(stats, config)` mirrors `run_examiner`: `messages.parse` with a
`ProgresoResult` pydantic model, `MAX_TOKENS` sized for thinking plus payload,
one retry for client-side constraint violations, `--no-llm` skips it entirely.

Input is `ProgresoStats` serialised — **not** transcripts, and not the raw
`examiner.json` files. Counting stays deterministic and reproducible; the model
supplies judgment about which movements matter. This is `analiza` spec §5's
governing principle ("deterministic layer for trends, LLM layer for judgment")
applied to the new layer.

Sizing is not a constraint: ~60 sessions of aggregated stats is far smaller than
the ~30k tokens the raw `examiner.json` corpus would be, and that itself fits in
one call.

**As built (2026-08-10),** in `analiza/narrativa.py` — `progreso.py` declares
itself pure, so the call cannot live there. `ProgresoResult` is structured
rather than free prose: `lectura`, `patrones_prioritarios` (≤3, each a
`pattern_id` plus a one-line reason), `cautelas`, `enfoque_proxima_sesion`.

The shape is doing work. A single prose field would invite the model to recite
numbers, and the moment it recites them they stop being reproducible — the
separation this whole spec rests on. Citing faults by `pattern_id` rather than
by description means the note renders each label from the vocabulary, so a
tracked fault cannot be quietly renamed on its way to the page, and
`uncited_patterns` fails a response that names an id the aggregation never
recorded. The enum stops an id that does not exist; only the aggregation knows
which ids *this learner* has produced, so that check is client-side and routes
into the single retry. `cautelas` is a field rather than a hedge buried in the
prose because it is the part a learner most needs to see.

Below the minimum session count no call is made at all: declining to report is
Key Decision 5, and it should not cost a request to decline.

**Outputs**, following the existing layout (`note.output_base`, so vault and
plain-dir layouts both work):

- `{base}/Progreso/YYYY-MM-DD progreso.md`
- `{base}/analiza-raw/progreso-YYYY-MM-DD/{progreso,stats}.json`
- Nothing appended to `analiza-stats.csv`.

**Backfill:** `analiza backfill-patrones [--dry-run]` walks
`{base}/analiza-raw/*/examiner.json`, sends each `(patron, tipo, instancias)`
triple to the model for vocabulary assignment, and rewrites the file in place
with `pattern_id` added. Idempotent — files already carrying `pattern_id` are
skipped. This is the `analiza` spec §6 v1.2 "reprocessing from persisted raw
JSON" capability, arriving early because WS1 needs it.

### Confidence

**Level:** Medium

**Rationale:**

High on the mechanics. WS2 is pure functions over data already on disk. WS3 is
the examiner call shape, which now has a verified working implementation —
structured outputs, versioned prompt, `MAX_TOKENS` sized for default-on
thinking, single retry.

The Medium is WS1, and it is a modelling risk rather than an engineering one.
The vocabulary has to be granular enough that two sessions' worth of "the same
fault" collapse onto one id, and coarse enough that the model picks the same id
each time. Too coarse (`gramatica-preposiciones`) and everything collapses into
it, hiding exactly the change the report exists to show. Too fine
(`miedo-para-infinitivo`) and near-identical faults split across ids, and
recurrence reads as zero. The evidence in *Why* shows the model reclassifying
its own findings across runs on identical input; a vocabulary makes that
tractable but does not automatically make it stable.

Second uncertainty: whether an "improvement" is legible at all at this sample
size. `vad_transcript_gap_s` was 60.3s on the only real recording — a full
minute of detected speech barely transcribed — so per-session data quality
varies enough to swamp small real changes. The minimum-session gate and the
low-confidence flag are the mitigations, but the right thresholds are unknown
until there is history.

**Validate before proceeding:**

1. ~~**Vocabulary stability spike.**~~ **Run 2026-08-09 — passed.** 51 patterns
   + `otro`, three v3 runs over the stored 595s transcript:

   - **8 of 12 ids in all three runs** (Jaccard 0.67), against a v2 baseline
     that shared essentially nothing by string.
   - **Zero `otro`** — the vocabulary covers this learner's faults, so
     granularity is not so fine that findings fall off the list.
   - **Zero ids whose `tipo` moved between runs.** This is the design working:
     pinning the id made `tipo` follow it instead of floating, which is
     precisely the instability §Why documents.

   **The residual variance is the 10-pattern cap, not the vocabulary.** All
   three runs returned exactly 10 — the cap is binding every time — while ~12
   real faults compete for the slots, so the four rotating ids
   (`calco-estructura-enfatica`, `subjuntivo-tras-deseo`,
   `conector-ausente-o-repetido`, `confusion-pares-minimos`) are rank-boundary
   items, not mis-keyed ones.

   **Consequence for WS2, which this spec did not anticipate:** absence from a
   session is ambiguous — the fault may not have occurred, or may have ranked
   11th. So a "resolved" classification cannot be read off absence alone while
   the cap binds. OQ2's proposed rendering ("absent for N sessions" rather than
   a verdict) turns out to be load-bearing rather than stylistic, and WS2
   should additionally record whether each session hit the cap, so a run at
   10/10 can be treated as truncated rather than complete.

   **Second ambiguity, found running the backfill (2026-08-10):** the
   vocabulary itself is versionless. Running WS1's backfill over the stored
   session assigned "uso incorrecto de 'ninguno de planes' / doble negación" to
   `autocorreccion-excesiva` — wrong, because no entry covered quantifiers and
   indefinites; adding `cuantificadores-indefinidos` fixed it. So the
   vocabulary will keep growing, and a pattern absent from an older session may
   be absent only because its id did not exist yet. This is the same class of
   comparability hazard as `prompt_version` and `whisper_model`, and WS2 needs
   the same treatment: a vocabulary version recorded per session, and
   segmentation that refuses to read absence across a boundary where the id was
   unavailable. **A CSV column is the likely shape, which puts this in WS2's
   scope rather than WS1's.**

   **Both consequences landed in WS2 (2026-08-10)**, as the `vocab_version`
   column and the four-way conclusiveness test — see *Approach → As built*.
2. **Backfill dry run** over the stored corpus, hand-checked, to confirm ids are
   assigned sensibly and `otro` is not a dumping ground.
3. **Threshold calibration** deferred until ≥10 sessions exist. Ship the gates
   configurable with the proposed defaults and revisit; do not tune them
   against a corpus of one.

### Key Decisions

1. **Canonical `pattern_id` over LLM clustering at report time.** The rejected
   alternative — feed the report pass every `examiner.json` and let it decide
   which findings are the same fault — needs no schema change and no backfill.
   It was rejected because it asks the model to judge whether two prose strings
   describe the same fault, which is the judgment that already produced two
   different answers on one transcript. It also makes recurrence counts
   unreproducible, so they could never feed a trend line. The vocabulary moves
   that judgment to one place, versioned and inspectable.
2. **Aggregation feeds the LLM, not raw sessions.** Counting is deterministic
   and reproducible; narration is not, and must not be load-bearing for
   numbers.
3. **Windows, not regression lines.** With ~10–40 noisy points and varying topic
   difficulty, a fitted slope reads as more precision than exists.
4. **`tipo` is explicitly not trended.** It is demonstrably unstable run to run.
   `calcos_n` stays in the CSV as a per-session record but the report must not
   present its movement as a finding.
5. **Refusing to report is a feature.** Below the minimum session count the
   command produces the aggregation and declines the narrative. A confident
   story fitted to five sessions is worse than no story.
6. **First roadmap entry for `analiza`.** The track gets a `ROADMAP.md` row so
   the feature is discoverable where every other feature is; `docs/specs/analiza/spec.md`
   remains the track's design document and gains a cross-link.

### Testing Approach

Per `OVERVIEW.md` §Testing Suite: pytest under `tests/`, ruff + mypy in CI's
`checks` job. No database, no browser — `analiza` is standalone.

**`tests/test_analiza_progreso.py`** (new — pure functions, no API key):

- Metric windows: first-N vs last-N over synthetic rows; the
  "insufficient sessions" state below the threshold.
- Pattern recurrence: sessions-appeared-in, first/last seen, instance totals
  across synthetic `examiner.json` payloads; a pattern absent for N sessions
  classifies as resolved, and one seen in the last session does not.
- Segmentation: rows spanning a `prompt_version` boundary produce two segments,
  never one trend; same for `whisper_model`.
- Low-confidence flagging at the `vad_transcript_gap_s` threshold, both sides.
- Determinism: aggregating the same inputs twice is byte-identical.
- Minimum-session gate: below it, aggregation is written and no narrative is
  requested.

**`tests/test_analiza_examiner.py`** (extend):

- `pattern_id` is required and enum-constrained; an off-vocabulary id fails
  validation.
- The v3 prompt asset names `output_schema_v3.json` and states the `otro` rule
  (the existing drift guard, extended).
- Every `Patron.id` in the vocabulary appears in the generated `Literal`.

**`tests/test_analiza_backfill.py`** (new):

- Idempotency: a file already carrying `pattern_id` is skipped.
- `--dry-run` writes nothing.
- A malformed stored file fails that file without aborting the walk.

**Live validation** (not in CI, needs `ANTHROPIC_API_KEY`): the vocabulary
stability spike from *Validate before proceeding*, and one end-to-end
`analiza progreso` run once ≥8 sessions exist.

**Prompt validation, 2026-08-10 — run against a synthetic 14-session corpus**
(real history is one session, and the narrative gate is 8). The corpus was
shaped so every state the prompt has a rule about actually occurs: a
`prompt_version` frontera, one segment with a real trend and one too short for
a window, a persistent fault, a conclusively absent one, a non-conclusive one,
a low-confidence session, and two sessions at the pattern cap. The model
named its segment when citing a trend, refused to compare across the
frontera, wrote "insufficient, not stable", treated `no-concluyente` as *not*
progress and `ausente` as an observation rather than a verdict, cited only ids
present in the aggregation, and reproduced every number correctly. It also
noticed unprompted that the faults appearing in only two sessions were the two
capped ones.

One defect, fixed by prompt rule 8: the first run leaked JSON field names into
the prose (`sesiones_desde_ultima=0`). **This does not substitute for a run
over real history** — a synthetic corpus cannot show whether the reading is
*useful*, only whether it is honest.

**Fixtures:** synthetic CSV rows and `examiner.json` payloads written in the
test module, plus the one real stored session under `analiza-out/` for the
live spike. No new audio fixtures — this feature never touches audio.
