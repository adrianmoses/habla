# Architecture

<!-- status: inferred -->
| Field | Value |
|---|---|
| status | planned |
| created | 2026-04-19 |
| inferred-from | docker-compose.yml, api/main.py, api/routes/*, hable-ya/config.py, hable-ya/pipeline/*, hable-ya/learner/*, hable-ya/tools/schema.py, eval/run_eval.py, eval/scoring/*, eval/fixtures/schema.py, finetune/format.py, finetune/generate.py, scripts/fixtures/*, pyproject.toml, habla_fixture_spec.md |

> **Migration note (spec #015).** This document is `status: inferred` and was
> written against the on-device hable-ya. The cloud fork (#001–#012) replaced the
> three on-device models with managed APIs and deleted the fine-tune workstream.
> The **External Dependencies**, **Key Constraints**, and runtime **Data Flow**
> sections below have been updated to the cloud posture; the component map and
> implementation-status descriptions ("stubbed", `aiosqlite`, etc.) are `inferred`
> and predate later specs — a full re-baseline is separate future work.

## System Overview

`habla` (cloud fork of `hable-ya`) is composed of three logical systems that run independently:

1. **Runtime voice agent:** FastAPI app exposing a WebSocket that drives a Pipecat pipeline (OpenAI `gpt-4o-transcribe` STT → Claude `claude-sonnet-4-6` via `AnthropicLLMService` → Cartesia `sonic-3` TTS), with native `log_turn` tool-call handling and turn observation writing into a Postgres + Apache AGE learner profile. Silero VAD + SmartTurn v3 are local (CPU/ONNX); no local model server or GPU.
2. **Eval harness** (implemented): CLI that runs fixture conversations against the llama.cpp endpoint and scores responses on 7 pedagogical / tool-fidelity dimensions, with an Opus second-pass judge for recast quality and a comparator for baseline-vs-tuned runs.
3. **Data / fine-tuning pipeline** (implemented): Anthropic Batches API generates fixtures across category × CEFR-band matrices; validators screen for leakage and format issues; consolidated fixtures feed an SFT JSONL builder; training runs in a Jupyter notebook using Unsloth.

The three systems share: fixture schemas (`eval/fixtures/schema.py`), scoring heuristics and thresholds (`eval/scoring/*`, `eval/compare.py`), and the pedagogical system-prompt content (currently authoritative in `finetune/format.py`).

## Component Map

```
hable-ya/
├── api/                              FastAPI surface
│   ├── main.py                       App factory, router mount [implemented]
│   └── routes/
│       ├── health.py                 GET /health [implemented]
│       └── session.py                WS /ws/session [stub — NotImplementedError]
│
├── hable-ya/                         Runtime agent package
│   ├── config.py                     Pydantic Settings (db_path, host, port, llama_cpp_url) [implemented]
│   ├── db/
│   │   ├── connection.py             async Postgres pool (asyncpg) [stub — decided: Postgres + Apache AGE]
│   │   └── hable_ya_db.py            Learner DB access layer, incl. AGE graph queries [stub]
│   ├── learner/
│   │   ├── profile.py                Learner profile state [stub]
│   │   ├── errors.py                 Error-pattern tracking [stub]
│   │   ├── vocabulary.py             Vocab-produced tracking [stub]
│   │   └── themes.py                 THEMES_BY_LEVEL + get_session_theme() [partial — empty dict, NotImplementedError]
│   ├── pipeline/
│   │   ├── runner.py                 Pipecat pipeline composition [stub]
│   │   ├── prompts/
│   │   │   ├── builder.py            build_system_prompt() [stub]
│   │   │   └── register.py           REGISTER_BY_LEVEL, COLD_START_INSTRUCTIONS [partial — empty]
│   │   └── processors/
│   │       ├── tool_handler.py       Consumes [TOOL_CALL: log_turn] from LLM output [stub]
│   │       └── turn_observer.py      Writes turn observations into DB [stub]
│   └── tools/schema.py               HABLE_YA_TOOLS = [] [stub]
│
├── eval/                             Model eval harness
│   ├── run_eval.py                   Fixture runner: OpenAI-compat calls, scoring, aggregation [implemented]
│   ├── compare.py                    Baseline-vs-finetune diff, threshold-driven recs [implemented]
│   ├── judge_recasts.py              Opus second-pass recast judge with disk cache [implemented]
│   ├── fixtures/schema.py            Pydantic fixture models (standard + cold_start) [implemented]
│   ├── scoring/
│   │   ├── turn.py                   parse_tool_calls + score_turn (7 dims + 3 scores) [implemented]
│   │   ├── recast.py                 spaCy lemma-based recast heuristic [implemented]
│   │   ├── register.py               CEFR band heuristic [implemented]
│   │   └── language.py               contains_english() via langdetect [implemented]
│   └── agent/
│       ├── opus_judge.py             Session-outcome judge [stub]
│       ├── synthetic_learner.py      Simulated learner with error patterns [stub]
│       └── run_agent_eval.py         End-to-end agent-eval orchestrator [stub]
│
├── finetune/                         SFT dataset generation
│   ├── generate.py                   Orchestrate consolidate → format → write JSONL (3 of 8 categories) [implemented]
│   ├── format.py                     fixture→SFT; system prompt + forbidden phrases + per-band guidance [implemented; authoritative prompt]
│   ├── validate.py                   JSONL validation (tool-call parse, band/category tallies, strict mode) [implemented]
│   └── review/cli.py                 Interactive review TUI [stub]
│
├── scripts/
│   ├── download_model.py             HF-hub download of GGUF + HF weights [implemented]
│   ├── init_db.py                    [stub]
│   ├── benchmark_latency.py          [stub]
│   ├── benchmark_concurrency.py      [referenced in README, not present on disk]
│   ├── export_session.py             [stub]
│   ├── generate_eval_fixtures.py     Thin CLI over scripts/fixtures/* [implemented]
│   └── fixtures/
│       ├── generate_fixtures.py      Anthropic Batches submission, per-band per-category matrix [implemented]
│       ├── validate_fixtures.py      Pre-review validators [implemented]
│       ├── review_fixtures.py        Rich-TUI review skeleton [partial]
│       ├── consolidate_fixtures.py   _approved/ → canonical per-category JSON [implemented]
│       ├── backfill_legacy.py        One-off migration [implemented]
│       └── prompts/                  Per-category Opus generation prompts (9 files) [implemented]
│
├── notebooks/                        Interactive fine-tuning
│   └── gemma4_finetune.ipynb         Unsloth SFT trainer
│
├── models/                           Local model artifacts (untracked registry)
│   ├── gemma-4-e4b.gguf              Base GGUF
│   ├── gemma-4-e4b-hf/               Base HF weights
│   ├── gemma-4-e4b-lora/             LoRA adapter output
│   ├── gemma-4-e4b-finetuned/        Merged fine-tuned weights
│   └── gemma-4-e4b-finetuned_gguf/   Quantized fine-tuned for serving
│
├── tests/                            pytest suite (scoring/themes/validate/variance implemented; db/prompts/tools stubbed)
└── habla_fixture_spec.md             Authoritative fixture spec (200 fixtures, 8 categories)
```

## Data Flow

### Runtime voice session (target — not yet implemented)

```
Mic
 └─► Pipecat pipeline
      ├─► Silero VAD + SmartTurn v3 (local, CPU/ONNX)
      ├─► OpenAI transcription API (STT, gpt-4o-transcribe, user utterance in es/en)
      ├─► HableYaTurnObserver (prior-context state)
      ├─► System prompt builder (pipeline/prompts/builder.py)
      │     uses REGISTER_BY_LEVEL, COLD_START_INSTRUCTIONS,
      │     learner profile, THEMES_BY_LEVEL
      ├─► AnthropicLLMService → Claude (claude-sonnet-4-6)
      │     native structured tool-calling, tool_choice: auto
      ├─► log_turn function handler (register_function)
      │     consumes native function-call frames → learner profile updates
      ├─► Cartesia TTS (sonic-3)
      └─► Speaker

Learner profile writes (async):
 HableYaToolHandler
  └─► hable-ya/db/hable_ya_db.py (asyncpg → Postgres + Apache AGE)
       ├─► relational tables: sessions, turns, vocabulary, error observations
       └─► AGE graph: learner knowledge-graph model
             (strengths, weaknesses, current level, progression edges)
```

All components downstream of Pipecat are stubs today. `[INFERRED: uncertain — exact pipeline topology is derived from pipecat-ai conventions and the stub filenames; the real composition will be decided in runner.py]`.

### Model eval run (implemented)

```
fixtures JSON (eval/fixtures/*.json, 8 categories)
 └─► eval/run_eval.py
      ├─► render conversation prior turns as messages
      ├─► Anthropic SDK → Claude (claude-sonnet-4-6), native log_turn tool-calling (#012)
      ├─► eval/scoring/turn.py: parse_tool_calls + score_turn
      │     • recast_present (eval/scoring/recast.py, spaCy)
      │     • recast_explicit (pattern match)
      │     • register_correct (eval/scoring/register.py)
      │     • sentence_count_ok, question_count_ok
      │     • L1_in_response (eval/scoring/language.py)
      │     • error_repeated, log_turn_called, tool_args_correct
      ├─► optional: eval/judge_recasts.py (Opus second pass, disk cache)
      └─► aggregate by dimension / CEFR band / category → results.json

compare.py:
 minimal.json + full.json
  └─► per-dimension + per-band deltas, threshold recommendations
      (cloud framing: minimal-prompt ablation vs full runtime prompt, #012)
```

### Fixture pipeline (implemented)

```
scripts/fixtures/prompts/<category>.py (per-band prompt templates)
 └─► scripts/fixtures/generate_fixtures.py
      └─► Anthropic Batches API → _pending/ JSON fixtures
           └─► scripts/fixtures/validate_fixtures.py (leak / shape checks)
                └─► human review (review_fixtures.py skeleton + manual file moves)
                     └─► _approved/ per-category JSON
                          └─► scripts/fixtures/consolidate_fixtures.py
                               └─► eval/fixtures/<category>.json (canonical)
                                    └─► consumed by eval/run_eval.py (above)
```

> The downstream SFT / fine-tune stage (`finetune/`, the Unsloth training
> notebook, and the llama.cpp-served Gemma artifacts) was removed in #010/#011.
> The cloud fork evaluates Claude directly against the canonical fixtures.

## External Dependencies

**Services at runtime**
- **Anthropic API** — Claude (`claude-sonnet-4-6`) is the runtime LLM via Pipecat `AnthropicLLMService`; also drives the eval Opus judges and fixture generation. Requires `ANTHROPIC_API_KEY`.
- **OpenAI API** — transcription (`gpt-4o-transcribe`) for STT. Requires `OPENAI_API_KEY`.
- **Cartesia API** — speech synthesis (`sonic-3`) for TTS. Requires `CARTESIA_API_KEY` + an owner-supplied `CARTESIA_VOICE_ID` (no default; fail-fast if unset).
- **PostgreSQL + Apache AGE** — persistence for learner state (relational) and the knowledge-graph learner model (AGE). Runs as the `db` compose service (image `apache/age:release_PG18_1.7.0`) alongside `app`.

The llama.cpp GPU server and the HuggingFace-gated Gemma download were removed in #009/#011; the runtime is CPU-only and needs no local model artifacts.

**Python runtime libraries (abridged)**
- **Voice:** pipecat-ai[silero,daily] with Silero VAD + SmartTurn v3 (local CPU/ONNX)
- **API:** fastapi, uvicorn, websockets
- **Model SDKs:** anthropic (Claude, core), openai (transcription), cartesia (TTS)
- **NLP heuristics (eval extra):** spacy (Spanish), langdetect
- **Persistence:** PostgreSQL + Apache AGE via the `asyncpg` driver (`database_url` in `config.py`). The legacy `aiosqlite` entry has been dropped.
- **Dev UX:** rich, pandas, pytest, ruff, mypy

**Build / deployment**
- Python ≥3.12, `uv` lockfile
- Docker Compose (`app` FastAPI + `db` Postgres/AGE) — no GPU, no model server
- Hatchling build backend (packages: `hable_ya`, `api`)

## Key Constraints

**Model constraints (from `hable_ya/config.py`)**
- LLM: Claude `claude-sonnet-4-6` via `AnthropicLLMService`; `llm_max_tokens = 1024` (room for a short spoken reply + native `log_turn` args); thinking disabled for voice latency.
- STT: OpenAI `gpt-4o-transcribe`, Spanish; TTS: Cartesia `sonic-3` with an owner-supplied `cartesia_voice_id`.
- CPU-only app container; no GPU reservation, no local model server.
- **Latency floor (measured, #013 — `scripts/benchmark_latency.py`, 20 iters):** per-stage TTFB p50/p95 ms — STT 711/1229, LLM TTFT 1179/1581, TTS 161/204; summed network floor ≈ 2.05s p50 / 3.0s p95, *before* the endpointing wait. This exceeds the p50≤1.5s / p95≤2.5s target on the network legs alone (dominated by LLM TTFT + STT), so endpointing was re-tuned only to not add to the floor: `smart_turn_stop_secs` 4.0→3.0 (trim the on-device carry-over ceiling; still bites only on uncertain/trailing learner turns), `vad_stop_secs` kept at 0.5. Getting under the target needs faster STT/LLM or streaming-partial STT — out of #013 scope.

**Pedagogical constraints (scoring thresholds in `eval/compare.py`, forbidden phrases in the runtime prompt under `hable_ya/pipeline/prompts/`)**
- `recast_present ≥ 0.70`, `recast_explicit ≤ 0.20`, `register_correct ≥ 0.70`, `L1_in_response ≤ 0.15`, `sentence_count_ok ≥ 0.75`, `question_count_ok ≥ 0.80`, `error_repeated ≤ 0.05`.
- Composite score = `0.7 * pedagogical + 0.3 * tool_fidelity`.
- Cold-start: `band_accuracy ≥ 0.75`, `MAE ≤ 0.20`.
- Responses must avoid explicit-correction phrases (enforced by the scoring heuristic and the runtime prompt's forbidden-phrase list).
- Recast form must appear verbatim (modulo grammatical person) in the agent response.

**Configuration (from `hable_ya/config.py` and `.env.example`)**
- `database_url` — Postgres DSN (default `postgresql://hable_ya:hable_ya@localhost:5433/hable_ya`); compose overrides to `db:5432` in-container. `db_pool_*` tune the asyncpg pool.
- `host`, `port`, `log_level` — FastAPI bind
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID` — provider credentials (read from the standard unprefixed env vars, not `HABLE_YA_`)
- `llm_model_name`, `stt_model`, `cartesia_model`, `smart_turn_stop_secs`, `vad_stop_secs`, `audio_sample_rate` — model + turn-taking tunables

**Scope constraints (from project memory)**
- No fine-tuning — the cloud fork uses Claude via prompt + native tools; the `finetune/` package was removed in #011.
- "Baseline" now refers to the **minimal-prompt ablation** (`--minimal-prompt`: role-only system prompt, no register/recast/tool schema), measuring what the runtime prompt engineering buys — not an untuned Gemma checkpoint (#012).

**Scope decisions**
- **Single-tenant.** The runtime serves one learner per deployment; no tenant isolation, no per-tenant auth, no multi-user session routing.
- **Knowledge graph storage.** The learner model graph is stored in Apache AGE (Postgres extension), colocated with relational learner state in the same Postgres instance.

**Inferred uncertainties**
- `[INFERRED: uncertain]` — deployment target (edge device class, OS, memory budget) is not specified in the repo.
- `[INFERRED: uncertain]` — session lifecycle for `/ws/session` (reconnect/resume, session-id scheme) is undefined.
- `[INFERRED: uncertain]` — concrete AGE graph schema (node/edge labels for skills, concepts, errors, progression) is not yet designed.
