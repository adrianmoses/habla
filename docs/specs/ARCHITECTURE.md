# Architecture

| Field | Value |
|---|---|
| purpose | Technical orientation: how the systems are put together, what they depend on, what constrains them |
| verified-at | `19d2173` (2026-08-08, spec #029) |

> **What this document is.** The technical companion to
> [`OVERVIEW.md`](OVERVIEW.md). It maps directories to responsibilities,
> traces data flow, and records the constraints and schemas a change has to
> respect. It does **not** track per-file implementation status — that changes
> every commit, is answered by `git ls-files` and the test suite, and is the
> part of this document that went stale between #000 and #029 (see spec
> [029-orientation-docs](029-orientation-docs/spec.md)). Where you need to know
> whether something works, run its tests.

## System Overview

`habla` (cloud fork of `hable-ya`) comprises four systems that run
independently:

1. **Runtime voice agent** — a FastAPI app exposing a WebSocket that drives a
   Pipecat pipeline (OpenAI `gpt-4o-transcribe` STT → Claude `claude-sonnet-4-6`
   via `AnthropicLLMService` → Cartesia `sonic-3` TTS). Native `log_turn` tool
   calls feed a Postgres learner model; Silero VAD + SmartTurn v3 are local
   (CPU/ONNX), and there is no local model server or GPU.
2. **Web client** — a Vite + React SPA that opens the session WebSocket, streams
   PCM audio, and renders the learner's progress from the authed `/api/learner*`
   endpoints.
3. **Eval harness** — a CLI that runs fixture conversations against Claude and
   scores them on 7 pedagogical / tool-fidelity dimensions, with an Opus
   second-pass recast judge, plus a synthetic-learner agent eval that plays
   scripted personas through a full session.
4. **`analiza`** — a standalone offline CLI (`analiza` console script) for
   recorded-monólogo analysis. It shares spaCy and the Anthropic SDK with the
   runtime and is otherwise decoupled: no database, no shared process, its own
   config file. Spec: [`docs/specs/analiza/spec.md`](analiza/spec.md).

Systems 1–3 share the pedagogical contract: the `log_turn` tool schema
(`hable_ya/tools/schema.py`), the canonical prompt renderer
(`hable_ya/pipeline/prompts/render.py`), the fixture schemas
(`eval/fixtures/schema.py`), and the scoring thresholds (`eval/compare.py`).

## Component Map

Directories and what they are responsible for. No per-file status labels by
design — and written as full paths in a table rather than an indented tree so
that `tests/test_doc_paths.py` can check every row independently.

| Path | Responsibility |
|---|---|
| `api/main.py` | App factory, lifespan (pool, migrations), router mount |
| `api/routes/` | Health, session WebSocket, `/api/learner*`, dev-gated endpoints |
| `hable_ya/config.py` | pydantic-settings — every tunable and credential |
| `hable_ya/auth.py` | Shared-secret session / API token check |
| `hable_ya/db/` | asyncpg pool + AGE bootstrap; alembic env and versions |
| `hable_ya/learner/` | The learner model — ingest, repos, aggregation, reads |
| `hable_ya/learner/leveling/` | Band promote/demote policy and its DB writes |
| `hable_ya/pipeline/` | Pipecat composition and the STT/LLM/TTS services |
| `hable_ya/pipeline/prompts/` | System-prompt renderer, per-band register guidance |
| `hable_ya/pipeline/processors/` | In-pipeline observers (turns, emission, latency) |
| `hable_ya/runtime/` | Per-session in-memory state (observation ring, latency) |
| `hable_ya/tools/schema.py` | `HABLE_YA_TOOLS` — the `log_turn` tool schema |
| `web/src/routes/` | SPA screens: Home, Session, Progreso, Historial, Ajustes |
| `web/src/voice/` | WebSocket client, PCM capture, amplitude |
| `web/src/lib/` | API client, session-token handling, formatting, `history.pushState` router |
| `eval/scoring/` | Per-turn dimension scoring (recast, register, language) |
| `eval/agent/` | Synthetic-learner personas, Opus judge, orchestrator |
| `eval/fixtures/` | Canonical per-category fixture JSON + schemas |
| `analiza/` | Standalone monólogo-analysis CLI |
| `scripts/` | Operational + dev tooling: `scripts/init_db.py`, `scripts/backup_db.sh`, `scripts/restore_db.sh`, `scripts/benchmark_latency.py`, `scripts/seed_dev_learner.py`, fixture generation |
| `tests/` | pytest suite; `tests/e2e/` holds the Playwright checks |
| `docs/specs/` | This document, `OVERVIEW.md`, `ROADMAP.md`, numbered specs |
| `docs/artifacts/` | Inherited hable-ya design artifacts (reference only) |

Deployment lives at the repo root: `Dockerfile`, `docker-compose.yml`,
`docker-compose.prod.yml`, `Caddyfile`, `alembic.ini`.

## Data Flow

### Runtime voice session

```
Browser (web/) ──PCM over WebSocket──► /ws/session
 └─► Pipecat pipeline (hable_ya/pipeline/runner.py)
      ├─► transport.input()
      ├─► Silero VAD + SmartTurn v3 (local, CPU/ONNX)
      ├─► OpenAI transcription (STT, gpt-4o-transcribe)
      ├─► HableYaTurnObserver
      ├─► context aggregator (user)
      ├─► AnthropicLLMService → Claude (claude-sonnet-4-6)
      │     native structured tool-calling, tool_choice: auto
      ├─► LogTurnEmissionObserver (emission-rate accounting)
      ├─► Cartesia TTS (sonic-3)
      ├─► transport.output()
      └─► context aggregator (assistant)

System prompt is rendered once per session by
hable_ya/pipeline/prompts/render.py from the learner profile snapshot,
per-band register guidance, and the selected theme or conversation mode.

log_turn tool call
 └─► hable_ya/pipeline/log_turn_handler.py
      └─► hable_ya/learner/ingest.py — one transaction per observation
           ├─► relational: turns, error_counts, error_observations,
           │              vocabulary_items  (load-bearing)
           └─► AGE graph, after the relational commit — best-effort,
                  failures counted, never rolls back learner state (#022)

Session end
 └─► hable_ya/learner/leveling/ — rolling-window band promote/demote
```

Two per-session observers sit outside the pipeline list: `ResponseLatencyObserver`
(#024, learner time-to-first-word) and the per-stage latency observers enabled by
`latency_debug` (#013).

### Learner read path

```
web/ (Progreso, Historial, Ajustes)
 └─► GET /api/learner, /api/learner/sessions, /api/learner/band-history
     PATCH /api/learner            (display name, #021)
      └─► hable_ya/learner/read.py → Postgres relational tables

Dev-only inspection (dev_endpoints_enabled):
 /dev/learner       relational snapshot + graph summary (#022)
 /dev/observations  in-memory ring of recent log_turn payloads
```

### Model eval run

```
fixtures JSON (eval/fixtures/*.json, 8 categories)
 └─► eval/run_eval.py
      ├─► render conversation prior turns as messages
      ├─► Anthropic SDK → Claude, native log_turn tool-calling (#012)
      ├─► eval/scoring/turn.py: parse_tool_calls + score_turn
      │     • recast_present (eval/scoring/recast.py, spaCy)
      │     • recast_explicit (pattern match)
      │     • register_correct (eval/scoring/register.py)
      │     • sentence_count_ok, question_count_ok
      │     • L1_in_response (eval/scoring/language.py)
      │     • error_repeated, log_turn_called, tool_args_correct
      ├─► optional: eval/judge_recasts.py (Opus second pass, disk cache)
      └─► aggregate by dimension / CEFR band / category → results.json

eval/compare.py: minimal.json + full.json → per-dimension and per-band deltas
with threshold recommendations. "Baseline" is the minimal-prompt ablation
(role-only system prompt), measuring what the runtime prompt buys (#012).

eval/agent/: scripted personas play a full session against the agent;
eval/agent/opus_judge.py scores the session outcome.
```

### Fixture pipeline

```
scripts/fixtures/prompts/<category>.py (per-band prompt templates)
 └─► scripts/fixtures/generate_fixtures.py
      └─► Anthropic Batches API → _pending/ JSON fixtures
           └─► scripts/fixtures/validate_fixtures.py (leak / shape checks)
                └─► human review → _approved/ per-category JSON
                     └─► scripts/fixtures/consolidate_fixtures.py
                          └─► eval/fixtures/<category>.json (canonical)
```

### `analiza`

```
audio ─► preprocess ─► VAD ─► faster-whisper ─► deterministic metrics
                                              └─► Anthropic examiner (DELE B2)
                                                   └─► Obsidian note + stats row
```

Deterministic metrics are reproducible across months regardless of prompt or
model changes; anything requiring interpretation lives in the LLM layer and is
labelled as such. See its spec for the full contract.

## External Dependencies

**Services at runtime**
- **Anthropic API** — Claude (`claude-sonnet-4-6`) is the runtime LLM via Pipecat
  `AnthropicLLMService`; also drives the eval Opus judges, fixture generation, and
  the `analiza` examiner. Requires `ANTHROPIC_API_KEY`.
- **OpenAI API** — transcription (`gpt-4o-transcribe`) for STT. Requires
  `OPENAI_API_KEY`.
- **Cartesia API** — speech synthesis (`sonic-3`) for TTS. Requires
  `CARTESIA_API_KEY` + an owner-supplied `CARTESIA_VOICE_ID` (no default;
  fail-fast if unset).
- **PostgreSQL + Apache AGE** — persistence for learner state (relational) and
  the knowledge graph (AGE). Runs as the `db` compose service (image
  `apache/age:release_PG18_1.7.0`) alongside `app`.

The llama.cpp GPU server and the HuggingFace-gated Gemma download were removed in
#009/#011; the runtime is CPU-only and needs no local model artifacts.

**Python runtime libraries (abridged)**
- **Voice:** pipecat-ai[silero,daily] with Silero VAD + SmartTurn v3 (local CPU/ONNX)
- **API:** fastapi, uvicorn, websockets
- **Model SDKs:** anthropic (Claude, core), openai (transcription), cartesia (TTS)
- **Persistence:** asyncpg, alembic (sqlalchemy only in
  `hable_ya/db/alembic/env.py`)
- **NLP:** spacy + `es_core_news_sm` (runtime vocabulary tracking and eval
  recast scoring), langdetect
- **Dev UX:** rich, pandas, pytest, ruff, mypy

**Build / deployment**
- Python ≥3.12, `uv` lockfile; Hatchling build backend (packages: `hable_ya`,
  `api`, `analiza`)
- Docker Compose (`app` FastAPI + `db` Postgres/AGE) — no GPU, no model server
- Production overlay `docker-compose.prod.yml` + Caddy reverse proxy for TLS and
  `wss://`, serving the built SPA (#017/#018)
- Node ≥20 for the `web/` client build

## Key Constraints

**Model constraints (from `hable_ya/config.py`)**
- LLM: Claude `claude-sonnet-4-6` via `AnthropicLLMService`; `llm_max_tokens = 1024`
  (room for a short spoken reply + native `log_turn` args); thinking disabled for
  voice latency.
- STT: OpenAI `gpt-4o-transcribe`, Spanish; TTS: Cartesia `sonic-3` with an
  owner-supplied `cartesia_voice_id`.
- CPU-only app container; no GPU reservation, no local model server.
- **Latency floor (measured, #013 — `scripts/benchmark_latency.py`, 20 iters):**
  per-stage TTFB p50/p95 ms — STT 711/1229, LLM TTFT 1179/1581, TTS 161/204;
  summed network floor ≈ 2.05s p50 / 3.0s p95, *before* the endpointing wait.
  This exceeds the p50≤1.5s / p95≤2.5s target on the network legs alone
  (dominated by LLM TTFT + STT), so endpointing was re-tuned only to not add to
  the floor: `smart_turn_stop_secs` 4.0→3.0, `vad_stop_secs` kept at 0.5.
  Getting under the target needs faster STT/LLM or streaming-partial STT.

**Pedagogical constraints (thresholds in `eval/compare.py`, forbidden phrases in
`hable_ya/pipeline/prompts/`)**
- `recast_present ≥ 0.70`, `recast_explicit ≤ 0.20`, `register_correct ≥ 0.70`,
  `L1_in_response ≤ 0.15`, `sentence_count_ok ≥ 0.75`, `question_count_ok ≥ 0.80`,
  `error_repeated ≤ 0.05`.
- Composite score = `0.7 * pedagogical + 0.3 * tool_fidelity`.
- Cold-start: `band_accuracy ≥ 0.75`, `MAE ≤ 0.20`.
- Responses must avoid explicit-correction phrases (enforced by the scoring
  heuristic and the runtime prompt's forbidden-phrase list).
- Recast form must appear verbatim (modulo grammatical person) in the response.

**Configuration (from `hable_ya/config.py` and `.env.example`)**
- `database_url` — Postgres DSN (default
  `postgresql://hable_ya:hable_ya@localhost:5433/hable_ya`); compose overrides to
  `db:5432` in-container. `db_pool_*` tune the asyncpg pool, and
  `allow_default_db_credentials` must be set explicitly to run with the defaults
  (#017).
- `host`, `port`, `log_level` — FastAPI bind.
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`
  — provider credentials (standard unprefixed env vars, not `HABLE_YA_`).
- `llm_model_name`, `stt_model`, `cartesia_model`, `smart_turn_stop_secs`,
  `vad_stop_secs`, `audio_sample_rate` — model + turn-taking tunables.
- `session_auth_token` / `session_auth_disabled`, `session_idle_timeout_secs` —
  session auth and lifetime (#016).
- `profile_window_turns`, `profile_top_errors`, `profile_top_vocab`,
  `theme_cooldown` — what the learner snapshot surfaces to the prompt.
- `leveling_*`, `placement_min_valid_turns`, `default_learner_band` — band
  policy.
- `dev_endpoints_enabled`, `latency_debug`, `runtime_turns_path`,
  `observation_ring_size` — inspection surfaces.

**Scope decisions**
- **Single-tenant — a decided non-goal, not an unanswered question.** The runtime
  serves one learner per deployment (`learner_profile CHECK (id = 1)`); no tenant
  isolation, no per-tenant auth, no multi-user session routing. Spec #021 settled
  this and wrote down the reversal cost so it stops being re-derived from the
  schema: composite `(learner_id, …)` PKs on `error_counts` / `vocabulary_items`,
  an AGE graph re-model (per-learner counters sit on shared `VocabItem` /
  `ErrorPattern` nodes), a real auth system replacing the shared-secret boolean in
  `hable_ya/auth.py`, a new global concurrency/cost ceiling in place of #016's
  single active session, ~41 `WHERE id = 1`-class SQL sites, and login/logout in
  the SPA. The learner does have a name — `learner_profile.display_name`,
  nullable, set through `PATCH /api/learner` (#021) — but a name is not an
  account. See [021-learner-identity](021-learner-identity/spec.md) Key Decision 4.
- **Knowledge graph — an inspection artifact, not an adaptation input (#022).**
  The graph is stored in Apache AGE, colocated with relational learner state in
  the same Postgres instance. It is written on every turn and read by exactly one
  thing: `graph.graph_summary()`, surfaced on the dev-gated `/dev/learner`.
  **Every adaptive decision is relational** — prompt profile, theme selection,
  leveling and `/api/learner` all read Postgres tables. #022 measured the graph
  writes at ~3ms and ~59% of the ingest transaction (0.15% of a turn's latency
  budget) and moved them *after* the relational commit, best-effort with a
  `graph_failed` counter, so a decorative write cannot roll back load-bearing
  state. The graph keeps accumulating so a future spec inherits history rather
  than an empty graph; making it load-bearing would be a re-modelling spec, not a
  query (see the schema note below).
- **No fine-tuning.** The cloud fork uses Claude via prompt + native tools;
  `finetune/` was removed in #011. "Baseline" means the minimal-prompt ablation
  (`--minimal-prompt`), not an untuned checkpoint (#012).

### AGE graph schema (`learner_knowledge`)

Read out of `hable_ya/learner/graph.py`, which is the only writer. Four node
labels, three edge types:

| Node | Key property | Counter | Written by |
|---|---|---|---|
| `Learner` | `id` (always `1`) | — | `ensure_learner_node` |
| `Scenario` | `domain`, `band` | — | `ensure_scenario_nodes`, `link_session_to_scenario` |
| `VocabItem` | `lemma` | `production_count`, `last_seen_at` | `upsert_vocab` |
| `ErrorPattern` | `category` | `occurrences`, `last_seen_at` | `upsert_error_pattern` |

| Edge | Shape | Properties |
|---|---|---|
| `PRODUCED` | `(Learner)→(VocabItem)` | `last_at` |
| `MADE_ERROR` | `(Learner)→(ErrorPattern)` | `occurrences`, `last_at` |
| `ENGAGED_WITH` | `(Learner)→(Scenario)` | `last_at` |

Three properties of this model are worth knowing before proposing a query:

- **It is a star, not a network.** Every edge originates at `(:Learner {id: 1})`.
  There is no `VocabItem`↔`VocabItem`, `ErrorPattern`↔`ErrorPattern`, or
  `VocabItem`↔`Scenario` edge, so error co-occurrence — the traversal the graph
  was imagined for — returns nothing. `error_observations` joined on `turn_id`
  answers it in one query.
- **Counters are duplicated on node *and* edge**, and the node-level ones are
  global. `v.production_count` / `e.occurrences` sit on a shared node while
  `r.occurrences` sits on the per-learner edge. Harmless single-tenant; it is
  the concrete obstacle #021 Key Decision 4 recorded for multi-user, since two
  learners producing *viajar* would inflate one node.
- **`ENGAGED_WITH` keeps no history.** `MERGE … SET r.last_at` overwrites, so
  three engagements with one scenario leave one edge carrying only the latest
  timestamp — strictly less than the `sessions` table beside it.

The error counter is `occurrences`, not `count`, because AGE's cypher parser
rejects `SET x.count = …` — the identifier collides with the `count()`
aggregate. The relational `error_counts.count` column is unaffected.
