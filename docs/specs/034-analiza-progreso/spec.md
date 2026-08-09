# Spec: analiza progress-over-time reporting

| Field | Value |
|---|---|
| id | 034 |
| status | draft |
| created | 2026-08-09 |

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

- [ ] Every `ErrorRow` carries a `pattern_id` drawn from a curated vocabulary,
      with `otro` as the escape hatch; `patron` remains as the human-readable
      label and is the only carrier of meaning when `pattern_id` is `otro`.
- [ ] Re-running the examiner twice over one stored transcript yields the same
      `pattern_id` set for the faults both runs found — the instability
      demonstrated above is confined to `patron` prose and `tipo`.
- [ ] A backfill command assigns `pattern_id` to every stored `examiner.json`
      that predates the vocabulary, in place, without re-transcribing.
- [ ] `analiza progreso [--desde D] [--hasta D] [--ejercicio E]` reads
      `analiza-stats.csv` plus the `examiner.json` files in range and writes a
      progress note plus a machine-readable aggregation JSON.
- [ ] The aggregation is computed by pure functions with no LLM involvement and
      is byte-identical across repeated runs over the same inputs.
- [ ] Per-pattern recurrence reports, for each `pattern_id` seen: sessions
      appeared in, first seen, last seen, total instances, and a
      resolved/persistent classification.
- [ ] Metric trends compare a first window against a last window rather than
      fitting a line, and each is reported with the session count behind it.
- [ ] Sessions are segmented by `prompt_version` and `whisper_model`; a range
      spanning a boundary is reported per-segment and never as one trend.
- [ ] Sessions whose `vad_transcript_gap_s` exceeds a configurable threshold are
      flagged low-confidence in both the aggregation and the note.
- [ ] Below a configurable minimum session count the command declines to produce
      a narrative, states the count, and still writes the aggregation JSON.
- [ ] `--no-llm` produces the aggregation and a numbers-only note.
- [ ] The LLM pass receives the aggregation JSON, never raw transcripts, and
      returns a structured result validated against a pydantic model.
- [ ] No LLM prose is written to `analiza-stats.csv`.
- [ ] The progress prompt is a versioned asset with its version recorded in the
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

1. **Vocabulary size and authorship.** ~30–60 entries covering the recurring
   B2-learner faults, hand-curated like `conectores_b2.py`? Or seeded by
   clustering the stored `examiner.json` corpus first? *Proposed: seed from the
   corpus, then hand-edit — the corpus is small and already on disk, and a
   from-scratch list will miss this learner's actual faults.*
2. **Resolved threshold.** How many consecutive absent sessions before a pattern
   is "resolved"? *Proposed: configurable, default 3, and reported as "absent
   for N sessions" rather than as a verdict.*
3. **Minimum session count for a narrative.** *Proposed: 8, configurable. Below
   that, metric noise plausibly exceeds real change at 2–3 sessions/week.*
4. **Window shape for metric trends.** First third vs last third, or fixed
   first-N vs last-N? *Proposed: fixed N=5 with an explicit "insufficient
   sessions" state, so the comparison doesn't silently change meaning as
   history grows.*
5. **Should `pattern_id` also feed the CSV?** A per-session `patterns` column
   would make recurrence computable from the CSV alone, without opening every
   `examiner.json`. *Proposed: no — it would put a variable-length list in a
   columnar contract the spec describes as "numbers only". Deferred.*
6. **Does the vocabulary change require `examiner_v3`?** Adding a required field
   changes the output contract, so yes by the existing convention. Confirm the
   version bump is acceptable given `prompt_version` gates score comparability
   and v2 has one recorded session.

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

1. **Vocabulary stability spike.** With a draft vocabulary, run the v3 examiner
   3× over the one stored transcript and measure `pattern_id` agreement across
   runs. This is the direct repeat of the experiment that motivated the spec,
   and the pass condition for WS1. If agreement is poor, the vocabulary is at
   the wrong granularity — fix that before building WS2/WS3 on top.
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

**Fixtures:** synthetic CSV rows and `examiner.json` payloads written in the
test module, plus the one real stored session under `analiza-out/` for the
live spike. No new audio fixtures — this feature never touches audio.
