# Decision Record: Product/docs update — on-device → cloud posture

| Field | Value |
|---|---|
| id | 015 |
| status | implemented |
| created | 2026-07-06 |
| spec | [spec.md](./spec.md) |

---

## Context

The model-boundary migration (#001–#012) was fully landed, but every
consumer-facing doc still described the deleted on-device system. The concrete
breakage was worse than "stale prose": following the documented setup path led
nowhere — `README.md` instructed `python scripts/download_model.py` (deleted in
#011) and `docker compose up llama` (service deleted in #009; compose now has
only `app` + `db`), and `.env.example` documented `HABLE_YA_LLAMA_CPP_URL` /
`HABLE_YA_WHISPER_*` / `HABLE_YA_PIPER_*` / a `gemma-*` model name / `HF_TOKEN`,
none of which the current `hable_ya/config.py` reads — while omitting the three
provider keys the runtime actually requires. A developer copying `.env.example`
to `.env` got a runtime that fails fast on missing `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / `CARTESIA_*`.

Beyond correctness, the migration crossed a product boundary that was never
stated: under hable-ya, learner audio never left the device (an implicit
privacy property, and an explicit "Not a cloud-hosted service" non-goal in
`OVERVIEW.md`). Under habla, audio goes to OpenAI, transcripts to Anthropic, and
reply text to Cartesia. Recording that posture was the substantive,
non-mechanical part of the work.

This is the last item in the migration series; it documents the combined
outcome of #001–#012 and has no code dependents.

## Decision

Updated four documentation surfaces — `.env.example`, `README.md`,
`OVERVIEW.md`, `ARCHITECTURE.md` — to the cloud posture, plus flipped the
`ROADMAP.md` status. `.env.example` was rewritten to mirror `config.py`
field-for-field; `README.md` was rewritten around the cloud stack (Claude /
OpenAI transcription / Cartesia) with a working run path against the current
compose; the posture / dependency / data-flow / constraint sections of
`OVERVIEW.md` and `ARCHITECTURE.md` were corrected; and a **privacy statement**
(audio→OpenAI, transcript→Anthropic, reply→Cartesia leave the device) was added
to `OVERVIEW.md` as an inverted non-goal.

No code, compose, or config defaults were touched — the change is docs +
`.env.example` only, verified by `git status` showing only those files plus the
new spec dir. Every factual claim was sourced from in-repo truth (`config.py`,
`docker-compose.yml`, the #001–#012 decision records), not from memory.

The edits to `OVERVIEW.md` / `ARCHITECTURE.md` were deliberately **scoped to the
cloud posture** — deployment surface, dependency surface, runtime data flow, and
the privacy statement — and explicitly did **not** re-baseline those docs'
`status: inferred` implementation-status descriptions (which are stale on axes
beyond this migration, e.g. "stubbed runtime" language predating specs 029/049).
A migration note was added to the top of each so the mixed currency is
self-documenting rather than misleading.

---

## Alternatives Considered

### Scope of the `OVERVIEW.md` / `ARCHITECTURE.md` edits

**Option A — posture-only, with a migration note (chosen).** Correct only the
on-device-vs-cloud claims, deployment/dependency surface, data flow, and add the
privacy statement; leave the broader `inferred` staleness for a future
re-baseline, flagged by a note.
- Pros: keeps #015 owning exactly what the roadmap line names; bounded, low-risk;
  no scope creep into features #015 doesn't own; every edit traceable to a
  migration fact.
- Cons: the docs remain internally inconsistent on the implementation-status
  axis after this lands.

**Option B — full re-baseline of both design docs.** Rewrite the component map,
stubbed-vs-implemented status, learner-model description, etc. to today's
reality.
- Pros: leaves the docs fully current.
- Cons: pulls in documentation work for specs 029/049/013/014 that #015 does not
  own; large, unbounded, and mixes concerns; harder to review as "the migration
  posture update."

**Chosen:** A. The migration note makes the mixed currency explicit, which is
honest and cheap; the full re-baseline is real work but belongs to its own item.

### `.env.example` in scope, despite the roadmap line naming only README + OVERVIEW

**Option A — include it (chosen).** Treat `.env.example` as part of the
"product/docs update."
- Pros: it is the concrete onboarding artifact and was actively wrong (its
  variables are ignored by `config.py`); fixing it is the difference between a
  working and a broken setup path — the feature's stated onboarding goal.
- Cons: technically beyond the literal roadmap wording.

**Option B — leave it, file a follow-up.** Stay strictly within "README +
OVERVIEW."
- Pros: literal adherence to the roadmap line.
- Cons: leaves the onboarding path broken, defeating the purpose of the feature.

**Chosen:** A. Low-risk mechanical fix with a clear single source of truth
(`config.py`); excluding it would make the rest of the doc work hollow.

### Historical eval / fine-tune references

**Option A — recontextualize, don't erase (chosen).** Keep the Gemma /
llama.cpp / Batches-pipeline mentions where they describe real project history
or the still-live eval harness; frame removed pieces as removed.
- Pros: doesn't misrepresent the project's history; the eval harness and fixture
  pipeline are genuinely still live (re-baselined in #012).
- Cons: requires per-mention judgment rather than a blanket delete.

**Option B — delete every on-device mention.** Scrub all Gemma/llama.cpp/finetune
references.
- Pros: simplest possible grep-clean result.
- Cons: erases real history and would wrongly delete the still-accurate eval /
  fixture-pipeline documentation.

**Chosen:** A. A "History" section in the README and "removed in #xxx" notes in
the design docs preserve provenance while making current-state unambiguous.

---

## Tradeoffs

- **Documentation currency is now uneven by design.** `OVERVIEW.md` /
  `ARCHITECTURE.md` are accurate on the cloud posture but still `inferred` and
  stale on implementation-status. This was accepted and flagged (migration
  notes) rather than fixed, to keep the feature bounded. Cost: a reader must
  heed the migration note; benefit: #015 stayed reviewable and didn't absorb
  other features' doc debt.
- **No automated test protects these docs.** They are prose + an example env
  file; the pytest suite has no assertions over them, so future drift will not
  be caught by CI. Mitigated by sourcing every claim from `config.py` /
  `docker-compose.yml` (which *are* covered) and by the grep/diff verification
  below — but re-drift is possible if the code changes again without a doc pass.
- **Privacy statement is factual, not legal.** It states the data-flow reality
  (utterances leave the device to named providers) and deliberately makes no
  DPA / retention / residency claim, since none is established in the repo.
  Optimizes for accuracy over marketing comfort.

---

### Spec Divergence

The implementation matched the spec. All acceptance criteria were met as
written, the two Open Questions were resolved along their proposed resolutions
(README keeps Eval + adds a short History section, drops Download/Serve-model;
privacy note enumerates the exact data flows), and no acceptance criterion was
dropped or reinterpreted.

| Spec Said | What Was Built | Reason |
|---|---|---|
| (no divergences) | Implementation followed the spec's five-step approach and both Open-Question resolutions verbatim | — |

One in-scope addition beyond the four named acceptance-criteria targets: the
spec's step 1–4 approach anticipated it, but two extra dangling on-device
references surfaced during editing and were fixed as migration-caused staleness —
the `finetune/format.py` citation in `OVERVIEW.md`'s DPO non-goal, and the
`eval/run_eval.py` → llama.cpp leg in `ARCHITECTURE.md`'s eval data-flow diagram
(re-pointed to the Anthropic SDK per #012). Both are squarely within the "correct
migration-stale facts" scope, not new scope.

---

## Spec Gaps Exposed

- **`OVERVIEW.md` / `ARCHITECTURE.md` need a full `inferred` re-baseline.** They
  remain stale beyond the cloud posture (e.g. "stubbed runtime", `aiosqlite`,
  schema-only learner model) despite specs 029/049 having landed real
  implementations. This is out of scope for #015 (documented as a non-goal +
  migration note) but is a genuine candidate for a future roadmap item: a
  design-doc re-baseline that reconciles the `inferred` docs with the
  now-implemented runtime.
- No errors were found in *this* spec; the gap is in the older `inferred` docs
  it deliberately did not fully rewrite.

---

## Test Evidence

This is a docs + `.env.example` change; "tests" are the spec's verification
gates (grep, env↔config diff, compose parse) plus the CI regression gates
confirming no code was affected.

**Gate 1 — no on-device tooling presented as a current requirement** (remaining
hits are the on-device *column* of the comparison table, the "no GPU required"
line, and the History section — all intentional):

```
$ grep -niE 'llama_cpp|faster-whisper|piper|download_model|HF_TOKEN|nvidia|\bGPU\b|whisper_|gemma' README.md .env.example
README.md:14:| LLM | fine-tuned Gemma 4 E4B via llama.cpp | **Claude** ... |
README.md:15:| STT | faster-whisper (CUDA) | **OpenAI transcription** ... |
README.md:16:| TTS | Piper | **Cartesia** (`sonic-3`) |
README.md:19:in-process. The runtime is CPU-only — no GPU required.
README.md:165:and the on-device serving tooling (`download_model.py`, the llama.cpp GPU compose
README.md:166:service, faster-whisper / piper) were removed in the migration — see
# (no hits in .env.example)
```

**Gate 2 — `.env.example` vars all map to `config.py` `Settings` fields, no
stale vars:** every emitted var (`HABLE_YA_HOST/PORT/LOG_LEVEL`,
`HABLE_YA_DATABASE_URL` + `DB_POOL_*`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`, `HABLE_YA_LLM_MODEL_NAME`,
`HABLE_YA_LLM_MAX_TOKENS`, `HABLE_YA_STT_MODEL`, `HABLE_YA_CARTESIA_MODEL`,
`HABLE_YA_SMART_TURN_STOP_SECS`, `HABLE_YA_VAD_STOP_SECS`,
`HABLE_YA_AUDIO_SAMPLE_RATE`) resolves to a field; the removed llama/whisper/
piper/HF vars are gone.

**Gate 3 — compose parses and matches README:**

```
$ docker compose config >/dev/null && echo OK
compose OK          # services: app, db (no llama)
```

**Regression gates — no code touched, CI scope stays green:**

```
$ git status --short
 M .env.example
 M README.md
 M docs/specs/ARCHITECTURE.md
 M docs/specs/OVERVIEW.md
 M docs/specs/ROADMAP.md
?? docs/specs/015-cloud-docs/

$ uv run ruff check hable_ya/ api/ eval/agent/ tests/ scripts/
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 54 source files

$ uv run pytest -q
258 passed, 52 skipped, 9 warnings in 16.68s
```

(Unscoped `mypy .` reports 3 pre-existing errors in `tests/test_tools.py` /
`tests/test_compose.py` — outside CI's `hable_ya/ api/ eval/agent/` scope and
untouched by this change.)
