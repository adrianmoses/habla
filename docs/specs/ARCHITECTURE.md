# Architecture

<!-- status: inferred -->
| Field | Value |
|---|---|
| status | planned |
| created | 2026-04-19 |
| inferred-from | docker-compose.yml, api/main.py, api/routes/*, hable-ya/config.py, hable-ya/pipeline/*, hable-ya/learner/*, hable-ya/tools/schema.py, eval/run_eval.py, eval/scoring/*, eval/fixtures/schema.py, finetune/format.py, finetune/generate.py, scripts/fixtures/*, pyproject.toml, habla_fixture_spec.md |

## System Overview

`hable-ya` is composed of three logical systems that share a model artifact but otherwise run independently:

1. **Runtime voice agent** (stubbed): FastAPI app exposing a WebSocket that drives a Pipecat pipeline (whisper STT → llama.cpp-served Gemma 4 → piper TTS), with tool-call handling and turn observation writing into a SQLite-backed learner profile.
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
      ├─► Silero VAD
      ├─► faster-whisper (STT, user utterance in es/en)
      ├─► HableYaTurnObserver (prior-context state)
      ├─► System prompt builder (pipeline/prompts/builder.py)
      │     uses REGISTER_BY_LEVEL, COLD_START_INSTRUCTIONS,
      │     learner profile, THEMES_BY_LEVEL
      ├─► OpenAI client → llama.cpp /v1/chat/completions
      │     serves gemma-4-e4b-finetuned_gguf
      ├─► HableYaToolHandler
      │     parses [TOOL_CALL: log_turn]{...} from response
      │     dispatches to learner profile updates
      ├─► piper-tts (TTS)
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
      ├─► openai.ChatCompletion → llama.cpp endpoint
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
 baseline.json + finetuned.json
  └─► per-dimension + per-band deltas, threshold recommendations
```

### Fixture + SFT pipeline (implemented)

```
scripts/fixtures/prompts/<category>.py (per-band prompt templates)
 └─► scripts/fixtures/generate_fixtures.py
      └─► Anthropic Batches API → _pending/ JSON fixtures
           └─► scripts/fixtures/validate_fixtures.py (leak / shape checks)
                └─► human review (review_fixtures.py skeleton + manual file moves)
                     └─► _approved/ per-category JSON
                          └─► scripts/fixtures/consolidate_fixtures.py
                               └─► eval/fixtures/<category>.json (canonical)

canonical fixtures
 └─► finetune/generate.py (3 of 8 categories: recast + multi_error + tool_call_correctness)
      └─► finetune/format.py: fixture_to_sft (system prompt + turns + tool call target)
           └─► finetune/datasets/*.jsonl
                └─► finetune/validate.py (JSONL sanity)
                     └─► notebooks/gemma4_finetune.ipynb (Unsloth SFT)
                          └─► models/gemma-4-e4b-finetuned/
                               └─► convert → models/gemma-4-e4b-finetuned_gguf/
                                    └─► served by llama.cpp (docker-compose)
```

## External Dependencies

**Services at runtime**
- **llama.cpp server** (`ghcr.io/ggml-org/llama.cpp:server-cuda`) — OpenAI-compatible endpoint on :8080, requires NVIDIA GPU, mounts `./models` into `/models`.
- **PostgreSQL + Apache AGE** — persistence for learner state (relational) and the knowledge-graph learner model (AGE). Will need to be added to `docker-compose.yml` alongside `app` and `llama`.
- **Anthropic API** — used only during fixture generation, recast judging, and (future) agent eval. Requires `ANTHROPIC_API_KEY`.
- **HuggingFace Hub** — gated Gemma downloads (`HF_TOKEN` / `huggingface-cli login`).

**Python runtime libraries (abridged)**
- **Voice:** pipecat-ai[silero,daily], faster-whisper, piper-tts
- **API:** fastapi, uvicorn, websockets
- **LLM client:** openai (targeted at llama.cpp), anthropic (eval/finetune only)
- **ML:** transformers, torch, unsloth, datasets, huggingface_hub (finetune extra)
- **NLP heuristics:** spacy (Spanish), langdetect
- **Persistence (decided, not yet wired):** PostgreSQL + Apache AGE graph extension (likely `asyncpg` driver). The `aiosqlite` entry in `pyproject.toml` is legacy and will be replaced.
- **Dev UX:** rich, pandas, pytest, ruff, mypy

**Build / deployment**
- Python ≥3.12, `uv` lockfile
- Docker Compose (`app` FastAPI + `llama` llama.cpp CUDA)
- Hatchling build backend (packages: `hable-ya`, `api`)

## Key Constraints

**Model-serving constraints (from `docker-compose.yml`)**
- Gemma 4 E4B quantized to Q8_0 GGUF.
- `--n-gpu-layers 99` (full offload), `--parallel 4`, `--ctx-size 16384`, `--cont-batching`.
- Single GPU reservation; no multi-GPU topology.

**Pedagogical constraints (scoring thresholds in `eval/compare.py`, forbidden phrases in `finetune/format.py`)**
- `recast_present ≥ 0.70`, `recast_explicit ≤ 0.20`, `register_correct ≥ 0.70`, `L1_in_response ≤ 0.15`, `sentence_count_ok ≥ 0.75`, `question_count_ok ≥ 0.80`, `error_repeated ≤ 0.05`.
- Composite score = `0.7 * pedagogical + 0.3 * tool_fidelity`.
- Cold-start: `band_accuracy ≥ 0.75`, `MAE ≤ 0.20`.
- Responses must avoid explicit-correction phrases (enforced by both scoring heuristic and SFT forbidden-phrase list).
- Recast form must appear verbatim (modulo grammatical person) in the agent response.

**Configuration (from `hable-ya/config.py` and `.env.example`)**
- `db_path` — legacy SQLite path; will be replaced by a Postgres DSN (e.g. `database_url`) once the DB layer is built
- `host`, `port` — FastAPI bind
- `llama_cpp_url` — default `http://localhost:8080` for the llama.cpp endpoint
- `HF_TOKEN`, `ANTHROPIC_API_KEY` — env vars for downloads and fixture/judge calls

**Scope constraints (from project memory)**
- SFT only — no DPO pipeline even though `fixture_to_dpo()` exists as scaffolding.
- Fine-tuning dataset is intentionally narrow: only `single_error_recast`, `multi_error`, and `tool_call_correctness` categories, because those are the categories that move the `recast_present` and `tool_args_correct` metrics.
- "Baseline" refers to the untuned Gemma 4 model state, not to a frozen fixture set; fixtures are renewable.

**Scope decisions**
- **Single-tenant.** The runtime serves one learner per deployment; no tenant isolation, no per-tenant auth, no multi-user session routing.
- **Knowledge graph storage.** The learner model graph is stored in Apache AGE (Postgres extension), colocated with relational learner state in the same Postgres instance.

**Inferred uncertainties**
- `[INFERRED: uncertain]` — deployment target (edge device class, OS, memory budget) is not specified in the repo.
- `[INFERRED: uncertain]` — session lifecycle for `/ws/session` (reconnect/resume, session-id scheme) is undefined.
- `[INFERRED: uncertain]` — concrete AGE graph schema (node/edge labels for skills, concepts, errors, progression) is not yet designed.
