# Spec: Product/docs update — on-device → cloud posture

| Field | Value |
|---|---|
| id | 015 |
| status | implemented |
| created | 2026-07-06 |

---

## Why

The code migration from on-device models to managed cloud APIs is complete
(#001–#012): the LLM is Claude via Pipecat's `AnthropicLLMService`, STT is the
OpenAI transcription API, TTS is Cartesia, the llama.cpp GPU service and the
fine-tune/on-device tooling are deleted, and the eval harness is re-baselined
against Claude. **The product-facing documentation was never updated to match.**

Every consumer-facing doc still describes the deleted on-device system as if it
were current:

- `README.md` tells a new user to install NVIDIA GPU support and `HF_TOKEN`,
  run `python scripts/download_model.py` (deleted in #011) and
  `docker compose up llama` (the `llama` service was deleted in #009 — compose
  now has only `app` + `db`), and to eval against a llama.cpp endpoint.
- `.env.example` documents `HABLE_YA_LLAMA_CPP_URL`, `HABLE_YA_WHISPER_*`,
  `HABLE_YA_PIPER_*`, a `gemma-4-e4b-finetuned` model name, and `HF_TOKEN` —
  **none of which `config.py` reads anymore.** The three keys the runtime now
  actually requires (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CARTESIA_API_KEY`
  + `CARTESIA_VOICE_ID`) are absent or commented out. A developer who copies
  `.env.example` to `.env` gets a runtime that fails fast on missing keys.
- `OVERVIEW.md` states as a **non-goal**: "Not a cloud-hosted service —
  deployment is local/on-device (llama.cpp server)." That is now the exact
  opposite of what the product is. Its tech-stack and target-consumer sections
  name the three on-device models.
- `ARCHITECTURE.md` documents a llama.cpp CUDA server, GPU reservations,
  faster-whisper/piper, and `HF_TOKEN`-gated Gemma downloads as live external
  dependencies.

Beyond correctness, the migration crosses a **product boundary that must be
stated explicitly: learner utterances now leave the device.** Under hable-ya,
audio never left the local machine — that on-device privacy posture was an
implicit selling point (and an explicit non-goal against cloud hosting). Under
habla, the learner's spoken audio goes to OpenAI (STT), the transcript goes to
Anthropic (LLM), and the agent's reply text goes to Cartesia (TTS). This is a
material change a user is entitled to know, and recording it is the substantive
(non-mechanical) part of this feature.

### Consumer Impact

- **Developer / operator onboarding (primary):** Today the documented setup path
  is broken end to end — GPU prerequisites that no longer apply, a model download
  that no longer exists, a compose service that was deleted, and an
  `.env.example` whose variables the app ignores. After this feature, a new
  operator can follow the README + `.env.example` and reach a running cloud
  session with the three real API keys.
- **End user / evaluator (privacy):** The on-device → cloud shift changes where
  learner audio and text go. This feature makes that posture explicit in
  `OVERVIEW.md` (privacy note + inverted non-goal) so it is a stated product
  property, not a buried consequence of a refactor.

### Roadmap Fit

Closes the migration series. #015 depends on #001–#012 being landed (it
documents their combined outcome) and has no code dependents. It is intentionally
last: the posture can only be described accurately once the model boundary,
deployment, dependency, and eval slices are all implemented. #013 (latency
re-benchmark) and #014 (resilience & cost) are independent runtime-hardening
items and are not blocked by or blocking this doc work.

---

## What

### Acceptance Criteria

- [ ] `README.md` describes the cloud stack (Claude / OpenAI Whisper / Cartesia)
      and contains **no** live instruction referencing a deleted artifact:
      `download_model.py`, `docker compose up llama`, GPU/NVIDIA prerequisites,
      `HF_TOKEN` as a runtime requirement, or the fine-tune notebook.
- [ ] `README.md` Setup lists the real required env vars (`ANTHROPIC_API_KEY`,
      `OPENAI_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`) and a working
      run path against the current `docker-compose.yml` (`app` + `db` only, no
      `llama`); `uv sync` guidance matches the current extras (no `--all-extras`
      requirement for the finetune extra, which was removed in #010).
- [ ] `.env.example` documents exactly the variables `hable_ya/config.py` reads:
      the three provider keys + `CARTESIA_VOICE_ID`, `HABLE_YA_DATABASE_URL`,
      host/port/log-level, and the turn-taking / audio knobs. The
      `LLAMA_CPP_URL`, `WHISPER_*`, `PIPER_*`, `LLM_MODEL_NAME=gemma-*`, and
      `HF_TOKEN` entries are removed.
- [ ] `OVERVIEW.md` no longer asserts "Not a cloud-hosted service"; the non-goals
      section reflects the cloud posture, and a **privacy note** states that
      learner audio (→ OpenAI), transcripts (→ Anthropic), and reply text
      (→ Cartesia) leave the device.
- [ ] `OVERVIEW.md` and `ARCHITECTURE.md` tech-stack / external-dependency
      sections name the cloud services (Claude, OpenAI transcription, Cartesia)
      and the retained local models (Silero VAD, SmartTurn v3), not
      faster-whisper / piper / llama.cpp-served Gemma, for the **runtime path**.
- [ ] References to Gemma / llama.cpp / Anthropic Batches that describe the
      *historical eval & fine-tune workstream* are preserved where still
      accurate, or clearly marked as historical — the docs must not read as
      though the on-device runtime still exists, but must not erase the project's
      history either.
- [ ] `grep -niE 'llama_cpp|faster-whisper|piper|download_model|HF_TOKEN|nvidia|
      \bGPU\b' README.md .env.example` returns no hit that is presented as a
      current runtime requirement.
- [ ] CI gates stay green (`pytest`, scoped `ruff`, scoped `mypy`) — this is a
      docs + `.env.example` change and must not touch code, but the repo must
      remain clean.

### Non-Goals

- **Not** a full re-audit of `OVERVIEW.md` / `ARCHITECTURE.md` to reflect every
  implemented feature. Those docs are `status: inferred` and stale on many axes
  beyond the cloud migration (e.g. they call the runtime "entirely stubbed" and
  the learner model "schema-only", though specs 029/049 landed a real learner
  model and leveling). This feature corrects **only the on-device-vs-cloud
  posture, the deployment/dependency surface, and the privacy statement.** A
  broader design-doc re-baseline is separate future work.
- **Not** a code change. No edits to `hable_ya/`, `api/`, `eval/`, config
  defaults, or compose. If a doc claim can only be made true by changing code,
  that is out of scope and gets flagged, not fixed here.
- **Not** removing the historical eval / fine-tune narrative. The Anthropic
  Batches fixture pipeline and the Opus judges are still real; the Gemma
  fine-tune is real project history. Recontextualize as history where needed;
  do not delete.
- **Not** adding new marketing/positioning copy beyond the factual posture and
  privacy statements.

### Open Questions

- **Q1 — README structure:** the current README is organized around the
  on-device model lifecycle (download → serve → eval → fine-tune). How much of
  the eval/fine-tune usage sections survive? *Resolution (proposed):* keep an
  "Eval" section (the harness is live, re-baselined in #012) and a short
  "History" note for the deleted fine-tune workstream; drop the "Download the
  model" and "Serve the model" sections. Deferred to implementation — low risk,
  reversible.
- **Q2 — privacy wording precision:** should the privacy note enumerate exact
  data flows (audio→OpenAI, text→Anthropic, reply→Cartesia) or stay high-level?
  *Resolution (proposed):* enumerate — it is accurate and more useful than a
  vague "uses cloud services" line. No legal/compliance claims (no DPA, no
  retention promises) are made, since none are established in the repo.

---

## How

### Approach

Pure documentation edit across four files. No code, no compose, no config
defaults change.

1. **`.env.example` (highest-value, most mechanical).** Rewrite to mirror
   `hable_ya/config.py::Settings` exactly. Sections: App (`HABLE_YA_HOST/PORT/
   LOG_LEVEL`), Postgres (`HABLE_YA_DATABASE_URL` + pool knobs, matching the
   compose note about `db:5432` in-compose vs `localhost:5433` on-host), the
   three provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID` — note voice_id has no default and
   the runtime fails fast without it), and turn-taking / audio
   (`HABLE_YA_SMART_TURN_STOP_SECS`, `HABLE_YA_VAD_STOP_SECS`,
   `HABLE_YA_AUDIO_SAMPLE_RATE`). Remove all llama.cpp / whisper / piper / HF
   entries. Source of truth is `config.py`, verified field-by-field.

2. **`README.md`.** Rewrite the intro paragraph (three on-device models → three
   managed APIs; keep Silero VAD + SmartTurn v3 as retained local models).
   Rewrite Setup: `uv sync` (drop `--all-extras`/GPU/`HF_TOKEN`), the three
   provider keys, `cp .env.example .env`. Replace "Download the model" /
   "Serve the model" with a single "Run" section pointing at
   `docker compose up` (`app` + `db`). Keep the "Run model eval" and "Inspect
   the learner model" sections (both still accurate — eval re-baselined in #012,
   learner DB live), updating the eval invocation to drop the llama.cpp
   `--base-url` framing per #012's re-pointed driver. Add a short "History"
   line noting the fine-tune/on-device workstream was removed in the cloud fork.

3. **`OVERVIEW.md`.** Update Product Summary and Tech Stack to the cloud stack.
   Invert the "Not a cloud-hosted service" non-goal to state the product **is**
   a cloud-API service and add the **privacy note** (learner audio/text leave
   the device: audio→OpenAI, transcript→Anthropic, reply→Cartesia). Leave the
   inferred-state caveats and the other non-goals (single-tenant, not-an-LMS,
   recast-only, Spanish-from-English) intact. Add a Revision-History-style note
   or update the header to point at the cloud fork.

4. **`ARCHITECTURE.md`.** Update the External Dependencies and Key Constraints
   sections: remove the llama.cpp CUDA server + GPU reservation entries and the
   HF-gated-Gemma download; add Anthropic / OpenAI / Cartesia as runtime
   services with their env-var requirements. Update the runtime data-flow block
   so the STT/LLM/TTS legs name the cloud services. Scope strictly to the
   model-boundary + deployment surface; do **not** rewrite the stubbed-runtime
   descriptions (Non-Goal).

5. **Cross-check `ROADMAP.md` link table** (already accurate for #001–#012) — no
   change beyond flipping #015 status.

### Confidence

**Level:** High

**Rationale:** The scope is a documentation edit whose source of truth is fully
in-repo and already read: `config.py` (real env vars), `docker-compose.yml`
(real services), and the #001–#012 decision records (what changed). There is no
external unknown, no code risk, and every acceptance criterion is checkable by
`grep` or by re-reading the four files against `config.py`. The only judgment
calls are wording (privacy note precision, how much eval/fine-tune narrative to
keep) and both are captured as Open Questions with proposed resolutions.

### Key Decisions

- **Scope the design-doc edits to posture only, not a full re-audit.**
  `OVERVIEW.md`/`ARCHITECTURE.md` are stale beyond the migration (stubbed-runtime
  language predates specs 029/049). Fixing all of that here would balloon #015
  into a doc rewrite spanning features it does not own. Trade-off: the docs
  remain internally inconsistent on the *implementation-status* axis after this
  lands. Accepted — flagged as future work; #015 owns only the cloud posture.
- **Recontextualize, don't erase, the fine-tune/eval history.** Gemma, llama.cpp,
  and the Batches fixture pipeline are real project history and the eval harness
  is still live. Deleting every mention would misrepresent the project. Keep
  historical references clearly framed as past/eval-only.
- **`.env.example` is in scope despite the roadmap line naming only README +
  OVERVIEW.** It is the concrete onboarding artifact and is actively wrong (its
  variables are ignored by the current `config.py`), so leaving it would defeat
  the feature's onboarding goal. Low-risk mechanical fix with a clear source of
  truth.

### Testing Approach

Docs-only; the pytest suite has no assertions over these files, so testing is
verification rather than new automated tests:

- **Grep gates** (per acceptance criteria): confirm no current-requirement
  mention of `llama_cpp` / `faster-whisper` / `piper` / `download_model` /
  `HF_TOKEN` / `nvidia` / `GPU` survives in `README.md` and `.env.example`.
- **`.env.example` ↔ `config.py` diff:** enumerate every `Settings` field and
  confirm each externally-set var appears in `.env.example`, and that no
  `.env.example` var is unread by `config.py`.
- **README run-path dry-check:** confirm the documented commands resolve against
  the repo — `docker compose config` parses, referenced scripts exist
  (`eval.run_eval` yes; `download_model.py` must be absent from instructions),
  and the compose services named in the README match `docker-compose.yml`
  (`app`, `db`).
- **Regression gates:** `pytest`, scoped `ruff`, scoped `mypy` remain green
  (no code touched — this confirms the change stayed within docs).
