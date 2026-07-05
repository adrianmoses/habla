# Overview

<!-- status: inferred -->
| Field | Value |
|---|---|
| status | planned |
| created | 2026-04-19 |
| inferred-from | README.md, pyproject.toml, habla_fixture_spec.md, api/main.py, eval/run_eval.py, eval/compare.py, eval/scoring/turn.py, finetune/format.py, finetune/generate.py, scripts/fixtures/*, hable-ya/config.py, docker-compose.yml |

## Product Summary

`hable-ya` is an on-device, voice-first Spanish language-acquisition agent. A single fine-tuned Gemma 4 E4B model acts simultaneously as conversational partner, pedagogical assessor, and adaptive engine. The runtime is a Pipecat STT → LLM → TTS pipeline (faster-whisper + Gemma served via llama.cpp + piper-tts), exposed as a FastAPI WebSocket. A knowledge-graph–based learner model (tracked via tool calls from the agent) captures strengths, weaknesses, CEFR level, and progression.

The repo today is structured as three parallel workstreams:
1. A model/eval workstream (complete) that scores model checkpoints against fixture conversations on pedagogical and tool-fidelity dimensions.
2. A fine-tuning workstream (complete) that generates SFT datasets from fixtures and runs Unsloth training in a notebook.
3. A runtime agent workstream (stubbed) that will wire the trained model into a Pipecat voice session with persistent learner state.

## Target Consumer

Two distinct consumer groups are inferable:

- **End user (runtime):** A Spanish learner (any CEFR band A1–C1) using a voice-only conversational partner on a local device. The device runs llama.cpp + Pipecat + piper/whisper; no cloud LLM dependency at inference time. `[INFERRED: uncertain — please verify target device class; README mentions "different devices" but no specific targets are in code]`.
- **Researcher / developer (model pipeline):** The project owner, iterating on the Gemma 4 E4B base model through fixture-driven eval, SFT dataset generation, and fine-tuning. This is the primary consumer today — almost all implemented code lives in `eval/`, `finetune/`, and `scripts/fixtures/`.

## Job To Be Done

Deliver a voice agent that **(a)** holds natural Spanish conversation, **(b)** implicitly corrects learner errors through recasts rather than explicit correction, **(c)** adapts register to the learner's CEFR band, **(d)** logs each turn to a structured learner profile via a tool call, and **(e)** cold-starts at an accurate band from a brief diagnostic.

The README's success definition operationalizes this as a composite score `0.7 * pedagogical + 0.3 * tool_fidelity`, with dimension-level thresholds that trigger fine-tuning vs. prompt-engineering decisions.

## Non-Goals

Inferred from code scope and explicit README statements:

- **Not** a cloud-hosted service — deployment is local/on-device (llama.cpp server).
- **Not** a text chat interface — the primary surface is voice (`/ws/session` WebSocket). `[INFERRED: uncertain — a text interface for dev/testing may be implied but is not present]`.
- **Not** an explicit-correction tutor — recasting is a core design constraint, scored negatively when the agent corrects explicitly.
- **Not** multi-language at launch — Spanish-from-English is the v1 target; the README mentions supporting other source/target pairs as a future process, not a v1 requirement.
- **Not** multi-tenant — the runtime is single-tenant (one learner per deployment). No tenant isolation, per-tenant auth, or multi-user session routing is planned.
- **Not** a full LMS — no lesson plans, no curriculum progression beyond the knowledge-graph learner model.
- **DPO fine-tuning is out of scope** for this repo despite `fixture_to_dpo()` existing in `finetune/format.py` (per project memory). SFT-only.

## Tech Stack

From `pyproject.toml` and `docker-compose.yml`:

- **Language / runtime:** Python ≥3.12, `uv` lockfile
- **API:** FastAPI + uvicorn, WebSocket via `websockets`
- **Voice pipeline:** `pipecat-ai[silero,daily]`, `faster-whisper` (STT), `piper-tts` (TTS)
- **LLM client:** `openai` SDK pointed at llama.cpp's OpenAI-compatible endpoint
- **Model serving:** llama.cpp CUDA server (Docker image `ghcr.io/ggml-org/llama.cpp:server-cuda`), Gemma 4 E4B GGUF, 99 GPU layers, 16384 ctx, 4-way parallel, continuous batching
- **Persistence (planned):** PostgreSQL with the [Apache AGE](https://age.apache.org/) extension for graph support of the learner model. The current `pyproject.toml` still lists `aiosqlite`; this is a known inconsistency to be replaced by an async Postgres driver (e.g. `asyncpg`). No DB code is implemented yet.
- **Config:** `pydantic-settings`, `python-dotenv`
- **Eval (optional extra):** `anthropic` (Opus judge), `spacy` (Spanish lemmatization for recast scoring), `langdetect`, `rich`, `pandas`
- **Fine-tune (optional extra):** `anthropic` (Opus-generated skeletons), `datasets`, `unsloth`, `transformers`, `torch`, `huggingface_hub`
- **Dev:** `pytest` + `pytest-asyncio`, `ruff` (line-length 88, py312), `mypy` strict

## Testing Suite

- **Runner:** pytest with `asyncio_mode = "auto"`, `testpaths = ["tests"]`.
- **Implemented tests:** `test_scoring.py` (comprehensive: tool-call parsing in 3 surface formats, recast heuristic, language detection, register), `test_themes.py`, `test_validate_fixtures.py`, `test_variance.py`.
- **Stubbed tests:** `test_db.py`, `test_prompts.py`, `test_tools.py` — docstrings only.
- **CI:** GitHub Actions workflow at `.github/workflows/ci.yml` runs `pytest`, scoped `ruff`, and scoped `mypy` on push to `main` and all PRs. Ruff/mypy coverage is intentionally scoped to paths whose lint/type debt has been paid down (`hable_ya/`, `api/`, and the voice-pipeline tests); other modules (`eval/`, `finetune/`, `scripts/fixtures/`) have pre-existing issues that are out of scope.

## Audit Notes

### Capabilities Observed

- Generates a fixture corpus via Anthropic Batches API across 8 categories (single_error_recast, multi_error, l1_handling, mimicry_cycle, register_boundary, tool_call_correctness, error_pattern_threshold, cold_start) and 5 CEFR bands.
- Validates fixtures (produced-form leaks, explicit-correction phrases, sentence/question counts, tool-call shape) and consolidates `_approved/` JSON into canonical per-category files.
- Runs model eval against a running llama.cpp OpenAI-compatible endpoint: calls the model on each fixture turn, parses tool calls from three surface formats, scores 7 dimensions plus composite score, aggregates by dimension / CEFR band / category.
- Second-pass recast judgment via Claude Opus with disk caching, integrated into heuristic scoring.
- Compares two eval runs (baseline vs fine-tuned), prints per-dimension and per-band deltas, and emits threshold-based recommendations (fine-tune / prompt-engineer / acceptable).
- Converts approved fixtures into SFT JSONL training examples with per-band register guidance and forbidden-phrase scrubbing.
- Validates generated SFT datasets (tool-call parsing, metadata tallies, strict-mode empty-field detection).
- Downloads Gemma 4 E4B in both GGUF and HF-weights format from Unsloth's HuggingFace repos.
- Serves a fine-tuned Gemma 4 E4B GGUF via llama.cpp CUDA (docker-compose).
- Exposes `/health` and a placeholder `/ws/session` FastAPI WebSocket endpoint.

### Gaps and Inconsistencies

- **Runtime pipeline is entirely stubbed.** `hable-ya/pipeline/runner.py`, `pipeline/prompts/builder.py`, `pipeline/processors/tool_handler.py`, `pipeline/processors/turn_observer.py`, and `api/routes/session.py` all raise `NotImplementedError` or are empty. The Pipecat voice loop does not exist yet.
- **Learner model is schema-only.** `hable-ya/learner/{profile,errors,vocabulary}.py` are docstrings; `themes.py` has an empty `THEMES_BY_LEVEL` and a NotImplementedError. No knowledge graph, no profile persistence, no error-pattern aggregation.
- **Database layer absent + dependency mismatch.** `config.db_path` exists and `aiosqlite` is currently vendored, but the decided DB is **PostgreSQL + Apache AGE** (graph extension) for the knowledge-graph learner model. `db/connection.py` and `db/hable_ya_db.py` are empty, no schema, no migrations, no init script (`scripts/init_db.py` is a stub). The SQLite-era dependency and config shape will need to be replaced.
- **Tool schema is empty.** `hable-ya/tools/schema.py` defines `HABLE_YA_TOOLS = []`, even though eval scoring and SFT formatting reference `log_turn` as a canonical tool call.
- **Register and prompt content empty.** `pipeline/prompts/register.py` has `REGISTER_BY_LEVEL = {}` with empty strings and `COLD_START_INSTRUCTIONS = ""`. The actual register guidance lives only in `finetune/format.py`.
- **Duplicated prompt-building logic.** `finetune/format.py` contains a fully-realized system prompt with register guidance, forbidden-phrase lists, and recast examples. A TODO notes that `pipeline/prompts/builder.py` will need to be unified with this. Today, any threshold/forbidden-phrase change must be applied in both places (and also in `eval/compare.py` threshold constants).
- **Agent-eval loop unimplemented.** `eval/agent/{opus_judge,synthetic_learner,run_agent_eval}.py` are stubs. The README describes a synthetic-learner + Opus-judge end-to-end eval that doesn't exist.
- **Benchmark + session-export scripts unimplemented.** `scripts/{benchmark_latency,benchmark_concurrency,export_session}.py` are stubs or absent; the README references `benchmark_concurrency.py` which does not exist on disk.
- **Review TUI partial.** `scripts/fixtures/review_fixtures.py` and `finetune/review/cli.py` have state scaffolding but no interactive UI; the effective workflow is manual file movement between `_pending/`, `_approved/`, `_rejected/`.
- **Model artifact provenance untracked.** `models/` contains at least `gemma-4-e4b.gguf`, `gemma-4-e4b-hf/`, `gemma-4-e4b-lora/`, `gemma-4-e4b-finetuned/`, and `gemma-4-e4b-finetuned_gguf/`. No registry links a checkpoint to its eval results or training dataset snapshot.
- **Dataset generation is narrower than spec.** `finetune/generate.py` runs only 3 of 8 categories (`single_error_recast`, `multi_error`, `tool_call_correctness`) — per project memory this is intentional scope (only the 3 that exercise the failing `recast_present` and `tool_args_correct` metrics), but the README reads as though all categories feed the SFT dataset.

### Uncertain Areas

- Target device class (README says "different devices" but no device profiles or build targets exist).
- Whether a text-chat dev surface is planned.
- Session lifecycle for the WebSocket endpoint (auth is out — single-tenant — but reconnect/resume semantics are undefined).
- Deployment path beyond local Docker Compose (no Kaggle/HF Space/app-bundle scaffolding present).
- Whether tests are run in CI anywhere (no CI config found).
