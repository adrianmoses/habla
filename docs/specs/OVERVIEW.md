# Overview

| Field | Value |
|---|---|
| purpose | Product orientation: what `habla` is, who it serves, what it deliberately does not do |
| verified-at | `19d2173` (2026-08-08, spec #029) |

> **What this document is.** The product-level entry point, alongside
> [`ARCHITECTURE.md`](ARCHITECTURE.md) (technical) and
> [`ROADMAP.md`](ROADMAP.md) (what is built and what is next). It records
> intent, consumers, and decided non-goals — claims that change when someone
> *decides* something, which makes a spec's decision record the moment to update
> them. It deliberately holds no inventory of which modules are implemented:
> `git ls-files` and the test suite answer that authoritatively, and a
> hand-copied second answer is what went stale between #000 and #029.

## Product Summary

`habla` is a cloud-API, voice-first Spanish language-acquisition agent — the
managed-API fork of the on-device [`hable-ya`](https://github.com/adrianmoses/hable-ya).
Claude acts simultaneously as conversational partner, pedagogical assessor, and
adaptive engine. The runtime is a Pipecat STT → LLM → TTS pipeline (OpenAI
`gpt-4o-transcribe` STT + Claude `claude-sonnet-4-6` via `AnthropicLLMService` +
Cartesia `sonic-3` TTS), exposed as a FastAPI WebSocket at `/ws/session` and
driven by a React SPA.

Silero VAD + SmartTurn v3 remain small local CPU/ONNX models in-process; the
runtime is otherwise CPU-only with no local model server.

A **relational** learner model (written from native `log_turn` tool calls the
agent emits each turn) captures strengths, weaknesses, CEFR band, and
progression. Every adaptive decision the runtime makes — prompt profile, theme
selection, leveling — reads Postgres tables (`learner_profile`, `turns`,
`error_counts`, `vocabulary_items`). An Apache AGE knowledge graph is written
alongside it and is an **inspection artifact, not an input to adaptation**;
#022 settled that after finding it read by nothing and unable to answer the
traversal queries it was imagined for.

## Systems

The repository contains four systems that run independently. See
[`ARCHITECTURE.md`](ARCHITECTURE.md) for how each is put together.

1. **Runtime voice agent** — `api/`, `hable_ya/`. The FastAPI app, the Pipecat
   session pipeline, the learner model and its migrations, and the authed
   `/api/learner*` read surface.
2. **Web client** — `web/`. A Vite + React SPA (session view, progress,
   history, settings), served behind the production reverse proxy.
3. **Eval harness** — `eval/`. Fixture-driven scoring of the agent on
   pedagogical and tool-fidelity dimensions, plus a synthetic-learner /
   Opus-judge agent eval.
4. **`analiza`** — `analiza/`. A standalone offline CLI, installed as its own
   console script, that turns a recorded Spanish monólogo into fluency metrics,
   DELE B2 examiner feedback, and an Obsidian note. It shares the repo's Spanish
   NLP and Anthropic dependencies and nothing else — no database, no runtime
   coupling. Spec: [`docs/specs/analiza/spec.md`](analiza/spec.md).

## Target Consumer

- **End user (runtime):** a Spanish learner (CEFR A1–C1) using a voice
  conversational partner through the browser client. Silero VAD + SmartTurn v3
  run locally; STT, the LLM, and TTS are managed cloud APIs, so learner audio
  and text leave the device at inference time — see the privacy non-goal below.
- **Owner / operator:** the single learner a deployment serves is also the
  person who runs it. This shapes the product more than any other fact: it is
  what makes single-tenancy a reasonable posture, what makes `/dev/*` endpoints
  and `scripts/seed_dev_learner.py` a legitimate inspection surface, and what
  makes a shared-secret session token a proportionate auth story.
- **Researcher / developer:** the project owner, iterating on the prompt and
  the pedagogical thresholds through the eval harness rather than on model
  weights — the cloud fork has no fine-tuning workstream.

## Job To Be Done

Deliver a voice agent that **(a)** holds natural Spanish conversation,
**(b)** implicitly corrects learner errors through recasts rather than explicit
correction, **(c)** adapts register to the learner's CEFR band, **(d)** logs
each turn to a structured learner profile via a tool call, and **(e)**
cold-starts at an accurate band from a brief diagnostic.

Success is operationalized as a composite score
`0.7 * pedagogical + 0.3 * tool_fidelity`, with dimension-level thresholds
(listed in [`ARCHITECTURE.md`](ARCHITECTURE.md) under Key Constraints) that
decide whether a gap is a prompt-engineering problem.

## Non-Goals

- **Cloud-API service (posture, not a non-goal).** `habla` deliberately depends
  on managed APIs at inference time (Claude / OpenAI / Cartesia) — the inverse of
  hable-ya's on-device stance. It is **not** on-device and **not** GPU-served;
  the app container is CPU-only (Postgres + AGE is the only other service).
- **Not privacy-preserving on-device.** As a direct consequence of the cloud
  posture, **learner utterances leave the device**: spoken audio goes to OpenAI
  (STT), the transcript goes to Anthropic (LLM), and the agent's reply text goes
  to Cartesia (TTS). No data-processing agreement, retention, or residency
  guarantee is claimed here — only that the data flow is off-device by design.
  Deployments with on-device privacy requirements should use hable-ya instead.
- **Not** a text chat interface — the primary surface is voice (`/ws/session`).
  The SPA carries no text-conversation mode.
- **Not** an explicit-correction tutor — recasting is a core design constraint,
  scored negatively when the agent corrects explicitly.
- **Not** multi-language — Spanish-from-English is the target; other
  source/target pairs are a future process, not a requirement.
- **Not** multi-tenant — the runtime is single-tenant (one learner per
  deployment, `learner_profile CHECK (id = 1)`). No tenant isolation, per-tenant
  auth, or multi-user session routing is planned. This is a **decided non-goal**,
  settled in spec #021 and costed there rather than left open: reversing it is
  five workstreams, not a variant of a feature. It needs composite
  `(learner_id, …)` primary keys on `error_counts` and `vocabulary_items` (today
  one learner's vocabulary table *is* the vocabulary table), a re-modeling of the
  AGE graph whose per-learner counters currently live on shared nodes, a real
  auth system in place of the shared-secret boolean in `hable_ya/auth.py`, a new
  global cost ceiling to replace #016's one-active-session bound, and
  login/logout plus per-user storage in the SPA. See
  [021-learner-identity](021-learner-identity/spec.md) Key Decision 4 for the
  full accounting. Against that, the product need it answers is one person's
  name in a greeting — which #021 delivers with a nullable column.
- **Not** a full LMS — no lesson plans, no curriculum progression beyond the
  learner model's band leveling.
- **Fine-tuning (SFT and DPO) is out of scope** for the cloud fork — the
  `finetune/` package was removed in #011. The model under test is Claude via
  prompt + native tools, not a tuned checkpoint. "Baseline" now means the
  minimal-prompt ablation (#012), not an untuned checkpoint.

## Tech Stack

From `pyproject.toml` and `docker-compose.yml`:

- **Language / runtime:** Python ≥3.12, `uv` lockfile
- **API:** FastAPI + uvicorn, WebSocket via `websockets`
- **Voice pipeline:** `pipecat-ai[silero,daily]` with Silero VAD + SmartTurn v3
  local (CPU/ONNX); STT/LLM/TTS are managed APIs
- **LLM:** `anthropic` (Claude `claude-sonnet-4-6`) via Pipecat
  `AnthropicLLMService`, native structured tool-calling for `log_turn`
- **STT / TTS:** `openai` (`gpt-4o-transcribe`) and `cartesia` (`sonic-3`) —
  managed APIs, no local model server or GPU
- **Persistence:** PostgreSQL + [Apache AGE](https://age.apache.org/) via
  `asyncpg`, with `alembic` migrations (`sqlalchemy` is pulled in by alembic and
  used only in `hable_ya/db/alembic/env.py`). Runs as the `db` compose service.
- **NLP:** `spacy` with `es_core_news_sm` — Spanish lemmatization for runtime
  vocabulary tracking and for eval recast scoring. The model is declared as a
  direct-URL wheel rather than a download step, because its absence degrades
  *silently* (vocabulary tracking records `[]`, indistinguishable from a learner
  who produced nothing).
- **Config:** `pydantic-settings`, `python-dotenv`; retries via `tenacity`
- **Web client:** Vite + React + TypeScript (`web/`), tested with vitest and
  Playwright
- **Optional extras:** `analiza` (`faster-whisper`, `typer`), `eval` (`rich`,
  `pandas`), `dev` (`pytest`, `pytest-asyncio`, `ruff`, `mypy`, `jsonschema`),
  `e2e` (`playwright` — separate from `dev` because it also needs a few hundred
  MB of browser)

## Testing Suite

- **Runner:** pytest with `asyncio_mode = "auto"`, `testpaths = ["tests"]`.
  Tests that touch the database use the `db` compose service; `tests/conftest.py`
  owns learner-state reset.
- **Layout:** `tests/` holds the Python suite (unit, DB-backed, and prompt
  byte-identity tests); `tests/e2e/` holds Playwright browser checks for the
  rendered SPA; `web/src/**/*.test.ts` holds the client's vitest unit tests.
- **Executable documentation:** `tests/test_readme_snippets.py` runs every SQL
  block in `README.md` (#022); `tests/test_doc_paths.py` checks that every
  repository path named in this document and in `ARCHITECTURE.md` exists (#029).
  Both exist because inspection is what let the documentation rot.
- **CI:** `.github/workflows/ci.yml` on push to `main` and all PRs, in three
  jobs — `checks` (ruff, mypy, pytest against a Postgres/AGE service), `web`
  (typecheck, build, vitest), and `e2e` (Playwright against the built SPA).
  Ruff/mypy coverage is intentionally scoped to paths whose lint/type debt has
  been paid down; `eval/` and `scripts/fixtures/` carry pre-existing issues.
