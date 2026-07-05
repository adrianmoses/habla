# Decision Record: On-Device Cleanup — Dependencies + Tooling

| Field | Value |
|---|---|
| id | 010 |
| status | implemented |
| created | 2026-07-05 |
| spec | [spec.md](./spec.md) |

---

## Context

With the model path fully cloud (specs 001/007/009), the tree still carried the
on-device apparatus — `faster-whisper`/`piper-tts` core deps, a `finetune` extra
(`torch`/`unsloth`/`transformers`/…), the `finetune/` package, `download_model.py`,
`benchmark_*`, `replay_placement.py`, and a fine-tune notebook — none of it used.
It also hid a real bug: `anthropic` is imported at runtime
(`services.py::warmup_llm`) but lived only in the `eval`/`finetune` extras, so a
plain `uv sync` produced an app that couldn't import. This slice deletes the dead
weight and fixes the dependency story. Implemented on branch
`spec-ondevice-cleanup-010-011`.

## Decision

`anthropic` is now a core dependency; `faster-whisper`, `piper-tts`, `jupyterlab`,
and the entire `finetune` optional-dependency group are removed; `anthropic` is
dropped from the `eval` extra (redundant once core). The `finetune/` package is
deleted, with its three `render_system_prompt` importers redirected to the symbol's
real home (`hable_ya.pipeline.prompts.render`); `download_model.py`, `benchmark_*`,
`replay_placement.py`, and the notebook are deleted, and the mypy/ruff config
entries for those paths are cleaned. `jsonschema` is declared as a dev dependency
(it had been present only transitively). The installed package now matches the
cloud runtime, and `uv sync` with no extras yields a runnable app.

---

## Alternatives Considered

### `finetune/` deletion vs. keeping a `format.py` stub

**Delete the package, redirect importers to `hable_ya` (chosen).**
`finetune/format.py` only re-exported `render_system_prompt` from
`hable_ya.pipeline.prompts.render`; three files imported it. Pointing them at the
source let the whole package go.
- Pros: no dead re-export module left behind; one obvious import source.
- Cons: touches three call sites (trivial, behavior-preserving).

**Keep a slimmed `finetune/format.py` re-export.** Rejected — it would preserve a
vestigial package for no reason once the training code is gone.

### `replay_placement.py` — remove here vs. defer to #012

**Remove here (chosen).** It's on-device eval tooling (targets the removed
llama.cpp endpoint) and was already broken against the removed
`settings.llama_cpp_url`. #011's charter is "remove on-device tooling," so it
fits; any cloud band-emission regression is #012's to design fresh, not a port of
this dead script.

### `jsonschema` / spaCy model — how to handle the surfaced gaps

Both were undeclared deps the removed torch/jupyterlab tree had been providing.
`jsonschema` (used by `test_tools.py`) is a genuine **test** dependency → declared
in the dev groups. The spaCy `es_core_news_sm` model is a **manual setup step**
(never a `pyproject` dep; CI installs it explicitly) → re-downloaded locally, no
`pyproject` change. Making the graph honest is exactly the point of the slice.

---

## Tradeoffs

- **Large `uv.lock` churn** — dropping the torch/unsloth/jupyterlab tree removed a
  big chunk of the lock. Expected; the clean-install check confirms coherence.
- **`eval/` still carries on-device references** — `run_agent_eval.py` still talks
  about a llama.cpp endpoint / `gemma-4-e4b` in its code and docstring. Out of
  scope here (only its stale *import* moved); the eval re-baseline is #012.
- **`finetune`/model-training is gone for good** — consistent with the cloud
  pivot (no fine-tuning in the cloud fork); recoverable from git history if ever
  needed.

---

### Spec Divergence

The implementation matched the spec, with one addition the gates forced.

| Spec Said | What Was Built | Reason |
|---|---|---|
| Remove deps / delete tooling as listed | Same, **plus** declaring `jsonschema` as a dev dep | It was only transitively installed via the removed tree; `test_tools.py` imports it, so the suite failed to collect until it was declared. A correct consequence of removing the hidden provider, not a scope change. |

---

## Spec Gaps Exposed

- **Two undeclared transitive dependencies** surfaced when the on-device tree was
  removed: `jsonschema` (test dep — now declared) and the spaCy `es_core_news_sm`
  model (manual setup step — re-downloaded; CI already handles it). No further
  action needed; noted so future removals expect to shake out hidden providers.
- **`eval/` cloud alignment remains open** for #012 (the harness still references
  llama.cpp / `gemma-4-e4b`).

---

## Test Evidence

Offline gates (spaCy `es_core_news_sm` re-installed as the documented setup step):

```
$ uv run pytest -q
254 passed, 52 skipped, 9 warnings in 10.20s

$ uv run ruff check hable_ya api eval/agent tests scripts
All checks passed!

$ uv run mypy hable_ya api eval/agent
Success: no issues found in 54 source files
```

The dependency-fix proof — a clean core-only install runs the app:

```
$ uv sync            # no extras
$ uv run python -c "import api.main"
api.main imports on core-only install OK
```

`import api.main` succeeding on a no-extras install is the direct evidence that
`anthropic` is now correctly a core dependency (it was previously only in the
`eval`/`finetune` extras).
