# Decision Record: GPU-Free Deploy + `.env` Loading

| Field | Value |
|---|---|
| id | 009 |
| status | implemented |
| created | 2026-07-05 |
| spec | [spec.md](./spec.md) |

---

## Context

With the LLM (spec 001) and STT/TTS (spec 007) on managed APIs, the runtime path
was already CPU-only — but the deploy still carried on-device GPU scaffolding: a
llama.cpp GPU compose service, an `nvidia` reservation on the `app` container,
and a `bootstrap_cuda()` re-exec in `api/main.py` whose sole purpose was putting
faster-whisper's cuBLAS/cuDNN on `LD_LIBRARY_PATH`. This slice deletes that so
the app runs on a plain CPU host, and folds in a gap both prior decision records
flagged: the app never loaded `.env` (`Settings` reads OS env only), so a
`uv run uvicorn` launch didn't see the provider keys specs 001/007 added.
Implemented on branch `spec-gpu-free-deploy-009`.

## Decision

The llama.cpp GPU compose service, the `app` `nvidia` GPU reservation, and its
`depends_on: llama` are removed (the `db` Postgres+AGE service is untouched).
`api/main.py` no longer imports or calls `bootstrap_cuda()`, and
`hable_ya/cuda_bootstrap.py` is deleted. `hable_ya/config.py` now calls
`python-dotenv`'s `load_dotenv()` at import (before the `settings` singleton),
with the default `override=False` so an exported or container-injected value
always wins over `.env`. The Dockerfile is unchanged — it was already
`python:3.12-slim` (CPU). The app is now CPU-only end to end.

---

## Alternatives Considered

### `.env` loading mechanism

**Option A — `python-dotenv` `load_dotenv()` in `config.py` (chosen).**
- Pros: populates `os.environ` for the whole process, so `Settings` *and* any
  library resolving keys from the environment both benefit; one line at the
  single config entrypoint; already a core dependency; `override=False` keeps
  real env authoritative.
- Cons: mutates process env (not just the `Settings` model).

**Option B — pydantic-settings `env_file` in `model_config`.**
- Pros: scoped to the `Settings` model.
- Cons: only feeds `Settings` (uses python-dotenv under the hood anyway); a
  library reading `os.environ` directly wouldn't see `.env`.

**Chosen: A** — the user asked to consider python-dotenv, and process-wide
loading is strictly more robust for a multi-SDK app.

### `load_dotenv()` placement

**`config.py` at import (chosen)** over `api/main.py` at startup. `config` is
the single place `Settings` is defined, so every importer — the app, the smoke
scripts, tests, a REPL — gets `.env` loaded without each remembering to call it.
Startup-only placement would miss non-app entrypoints.

### `cuda_bootstrap.py` — this slice vs #011

**Remove here (chosen).** It's GPU runtime plumbing, squarely the GPU-removal
theme of #009; leaving it for the #011 "remove on-device tooling" pass would
strand a dead re-exec shim in the tree across two more slices. Pulled forward
from #011 (roadmap rows adjusted). The `faster-whisper`/`piper-tts`/`torch`
*packages* stay for #010 — removing the module while the deps remain installed
is harmless (nothing imports it).

---

## Tradeoffs

- **`.env` now loads at `config` import** — including during tests, which loads
  the real `habla/.env` into `os.environ`. Safe because `override=False` means
  CI env and `monkeypatch` still win, and the config tests assert defaults or use
  explicit overrides; the new `.env` test isolates with `monkeypatch.delenv` + a
  temp file.
- **`faster-whisper`/`piper-tts`/`torch` remain installed** (unused) until #010 —
  a larger-than-necessary image until then, but nothing *runs* CUDA.
- **`.env` is a dev convenience only** — production still relies on real env /
  compose `env_file` / orchestrator secret injection.

---

### Spec Divergence

The implementation matched the spec exactly. No divergences.

| Spec Said | What Was Built | Reason |
|---|---|---|
| (matched) | Compose GPU/llama removal, `cuda_bootstrap` deletion, `load_dotenv()` in `config.py`, Dockerfile untouched | — |

---

## Spec Gaps Exposed

None new. This slice *closed* the `.env`-loading gap that specs 001 and 007
recorded. The `faster-whisper`/`piper-tts`/`torch` dependency pruning remains
tracked as #010, and `download_model.py` / `benchmark_*` / the `finetune/`
package / the notebook remain #011.

---

## Test Evidence

Offline gates:

```
$ uv run pytest -q
254 passed, 52 skipped, 9 warnings in 11.29s

$ uv run ruff check hable_ya api eval/agent tests scripts
All checks passed!

$ uv run mypy hable_ya api eval/agent
Success: no issues found in 54 source files
```

Deploy + import checks:

```
$ uv run python -c "import api.main; ..."
api.main OK; no cuda_bootstrap: True

$ docker compose config >/dev/null && echo "compose parses OK"
compose parses OK
```

`tests/test_compose.py` asserts the compose file has no `llama` service, no
`app` GPU `devices` reservation, and no `depends_on: llama`, with `db` still
present. `tests/test_config.py` asserts a temp `.env` reaches `Settings` and that
an exported var wins over `.env` (`override=False`).
