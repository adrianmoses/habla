# Spec: GPU-Free Deploy + `.env` Loading

| Field | Value |
|---|---|
| id | 009 |
| status | draft |
| created | 2026-07-05 |
| covers roadmap | #009 (+ the `.env`-loading gap surfaced by specs 001/007) |

---

## Why

With specs 001 and 007 all three models are managed APIs and the runtime path is
CPU-only — only Silero VAD + SmartTurn (small ONNX, CPU) remain local. But the
deploy still carries the on-device GPU scaffolding: `docker-compose.yml` runs a
`llama.cpp` GPU service and reserves an `nvidia` device for the `app` container,
and `api/main.py` re-execs the process through `bootstrap_cuda()` to put
faster-whisper's cuBLAS/cuDNN on `LD_LIBRARY_PATH`. None of that is needed
anymore, and it actively blocks the point of the cloud fork: you shouldn't need
an NVIDIA box to run a voice agent whose STT/LLM/TTS are all remote.

This slice removes that scaffolding so the app runs on a plain CPU host, and
folds in a small gap both prior decision records flagged: **the app never loads
`.env`**. `Settings` reads OS env only, so a `uv run uvicorn` launch doesn't see
the keys in `.env` unless they're separately exported — the very keys specs
001/007 added (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CARTESIA_API_KEY`,
`CARTESIA_VOICE_ID`). We fix it with `python-dotenv` (already a dependency).

### Consumer Impact

- **Project owner / operator:** Can `docker compose up` or `uv run uvicorn` on a
  CPU-only host — no GPU, no CUDA runtime, no llama.cpp container. And a local /
  bare-metal run picks up `.env` automatically instead of failing on empty keys
  or requiring a manual `export`. This is the first point the deploy actually
  matches the "cloud, serverless-friendly" product intent.
- **End user (learner):** No change — same voice loop.
- **Downstream:** Unblocks a genuinely CPU-only container image and simplifies
  #013 (latency benchmarking on commodity hosts). The `.env` fix makes every
  key-consuming path (LLM/STT/TTS) work from a single `.env` in dev.

### Roadmap Fit

Roadmap #009. Upstream: specs 001 (LLM) + 007 (STT/TTS) ✓ — nothing in the
runtime path uses CUDA once they landed, which is what makes this a safe,
mechanical removal. The `.env`-loading fix is a gap from those slices' decision
records, folded here because it's the same "make the cloud app actually
runnable" theme and touches `config.py` once. Boundary with **#010**: this slice
removes *deploy/GPU plumbing* (compose, `cuda_bootstrap`, the `bootstrap_cuda`
call); pruning the now-unused `faster-whisper` / `piper-tts` packages and
promoting `anthropic` / `cartesia` in `pyproject` is #010.

---

## What

### Acceptance Criteria

- [ ] `docker-compose.yml` no longer defines the `llama` (llama.cpp) service, and
  the `app` service has no `deploy.resources.reservations.devices` GPU
  reservation and no `depends_on: llama`. The `db` (Postgres + AGE) service is
  unchanged; the app still depends on `db` being healthy.
- [ ] `docker compose config` parses the file successfully (valid after the
  edits).
- [ ] `api/main.py` no longer imports or calls `bootstrap_cuda()`; its module
  docstring no longer references CUDA or llama.cpp warmup. The app imports and
  starts with no CUDA libraries present.
- [ ] `hable_ya/cuda_bootstrap.py` is deleted (its only caller was
  `api/main.py`, and it exists solely for faster-whisper's CUDA libs).
- [ ] `hable_ya/config.py` calls `python-dotenv`'s `load_dotenv()` at import,
  before the `settings` singleton is constructed, so a `.env` in the working
  directory populates the environment for `Settings` **and** any library reading
  `os.environ`. Existing real environment variables are not overridden (dev
  `.env` never clobbers a value the operator exported / the container injected).
- [ ] With a `.env` containing the provider keys and no vars exported, a fresh
  `Settings()` resolves `anthropic_api_key` / `openai_api_key` /
  `cartesia_api_key` / `cartesia_voice_id` from that file.
- [ ] `pytest` passes (including a guard that the compose file has no GPU/llama
  scaffolding and a test of the `.env` → `Settings` path); ruff + mypy clean.

### Non-Goals

- **No `pyproject` dependency changes** — removing `faster-whisper` / `piper-tts`
  and promoting `anthropic` / `cartesia` to core is **#010**. This slice leaves
  those installed-but-unused; the point here is that nothing *runs* CUDA.
- **No Dockerfile change** — it's already `python:3.12-slim` (CPU); there's no
  CUDA base or GPU install to strip. (Confirmed; noted so the absence is
  deliberate, not an oversight.)
- **No docs rewrite** — updating README/OVERVIEW for the cloud posture is #015.
  This slice may touch only comments in the files it edits.
- **No latency work** (#013) and **no VAD/SmartTurn change** — those stay local
  CPU models.
- **No secrets management** — `.env` is a dev convenience; production secret
  injection (compose `env_file`, orchestrator secrets) is out of scope.

### Open Questions

1. **`load_dotenv()` placement — `config.py` import vs `api/main.py` startup.**
   Recommend `config.py` (module import, before the singleton): it's the single
   place `Settings` is defined, so any importer — the app, the smoke scripts,
   tests, a REPL — gets `.env` loaded without each remembering to call it.
   Resolve in review; leaning `config.py`.

---

## How

### Approach

**Compose (`docker-compose.yml`).** Delete the entire `llama` service block.
From the `app` service remove the `deploy.resources.reservations.devices`
(nvidia) block and the `depends_on.llama` entry (keep `depends_on.db`
health-gated). Leave `db` and the `pgdata` volume as-is.

**App entrypoint (`api/main.py`).** Remove the top-of-file
`from hable_ya.cuda_bootstrap import bootstrap_cuda` + `bootstrap_cuda()` call
and the `# Must run before any pipecat/torch import` comment; rewrite the module
docstring (which still describes the llama.cpp ping + CUDA bootstrap) to reflect
the managed-API startup. Import ordering no longer needs the pre-import CUDA
shim, so the `# noqa: E402` dance can relax where it was only there for
`bootstrap_cuda`.

**Delete `hable_ya/cuda_bootstrap.py`.** Dead once the call is gone.

**`.env` loading (`hable_ya/config.py`).** Add near the top, after imports and
before the `Settings` class / `settings` singleton:
```python
from dotenv import load_dotenv

load_dotenv()  # dev convenience: populate os.environ from .env (no override)
```
`load_dotenv()` defaults to `override=False`, so an exported var or a
container-injected value always wins over `.env`. This feeds both the
`validation_alias` fields on `Settings` and any SDK that reads `os.environ`.

### Confidence

**Level:** High

**Rationale:** This is deletion of confirmed-dead scaffolding plus one
well-understood `python-dotenv` call. `cuda_bootstrap` has exactly one caller
(`api/main.py`), verified by grep; `python-dotenv` is already a dependency and
already used by the spike/smoke scripts; the Dockerfile is already a CPU base.
The only behavioral change is `.env` now loading — guarded to not override real
env, so it can't surprise CI or production.

**Validate before proceeding:** none required (High). Sanity checks live in the
acceptance criteria: `docker compose config` parses, the app imports without
CUDA, and the `.env` → `Settings` test passes.

### Key Decisions

1. **`python-dotenv` `load_dotenv()`, not pydantic-settings `env_file`.** Both
   would feed `Settings` (pydantic uses python-dotenv under the hood), but
   `load_dotenv()` populates `os.environ` for the whole process, so any library
   resolving keys from the environment benefits too — and it's one line at the
   single config entrypoint. `override=False` keeps real env authoritative.
2. **Delete `cuda_bootstrap.py` here (GPU plumbing), keep the deps for #010.**
   The module is GPU runtime scaffolding, squarely #009; the `faster-whisper` /
   `piper-tts` / `torch` *packages* are a `pyproject` concern for #010. Removing
   the module while leaving the deps installed is harmless — nothing imports it.
3. **Dockerfile untouched.** Already `python:3.12-slim`; there is no CUDA base or
   GPU tooling to remove. Recorded as a deliberate non-change.

### Testing Approach

Deploy/config changes are mostly structural; keep it to cheap, meaningful guards
plus the existing suite:

- **`tests/test_config.py`:** a `.env`-loading test — write a temp `.env` with a
  key, `load_dotenv()` it against a temp CWD (or `dotenv_path`), construct
  `Settings()`, assert the value flows through; and assert `override=False`
  semantics (a pre-set env var wins over `.env`).
- **`tests/test_compose.py` (new, lightweight):** parse `docker-compose.yml` as
  YAML and assert (a) no `llama` service, (b) the `app` service has no `devices`
  GPU reservation, (c) `db` still present. A structural regression guard so the
  GPU scaffolding can't silently return.
- **`tests/test_health.py`:** already imports `api.main` (patched) — confirm it
  still passes with `bootstrap_cuda` removed (no import error).
- **Manual (human-run):** `docker compose config` parses; `uv run uvicorn
  api.main:app` boots on a CPU-only host and `/health` reports ready with the
  keys resolved from `.env`.
