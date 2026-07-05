# Spec: On-Device Cleanup — Dependencies + Tooling

| Field | Value |
|---|---|
| id | 010 |
| status | approved |
| created | 2026-07-05 |
| covers roadmap | #010, #011 (bundle) |

---

## Why

The model path is fully cloud now (specs 001/007/009), but the tree still
carries the on-device apparatus: `pyproject` lists `faster-whisper` / `piper-tts`
as core deps and a whole `finetune` extra (`torch`, `unsloth`, `transformers`,
`datasets`, `huggingface_hub`); the `finetune/` package, `scripts/download_model.py`,
the `benchmark_*` scripts, and a Gemma fine-tune notebook still sit in the repo.
None of it runs anymore. Worse, there's a live bug: **`anthropic` — which the
runtime imports (`services.py::warmup_llm`) — is only in the `eval`/`finetune`
extras, not core**, so a plain `uv sync` produces an app that can't import. This
slice removes the dead weight and fixes the dependency story so the installed
package matches the cloud runtime.

Bundling #010 (deps) and #011 (tooling) because they're one motion: the code
being deleted (#011) is exactly what pulls the deps being dropped (#010), and
deleting the package without dropping the extra (or vice versa) leaves an
inconsistent half-state. One PR, one coherent "delete the on-device leftovers."

### Consumer Impact

- **Project owner / operator:** `uv sync` (no extras) yields a working cloud app
  — `anthropic` is a real dependency now, and multi-GB `torch`/`unsloth` no
  longer install by default, so a clean environment and the container image
  shrink substantially. The repo stops advertising a fine-tune/on-device story
  it no longer supports.
- **End user (learner):** No change.
- **Downstream:** Unblocks a lean image for deploy; leaves `eval/` intact for the
  #012 re-baseline (only its stale `finetune.format` import is redirected to the
  real source).

### Roadmap Fit

Bundles #010 + #011. Upstream: specs 001/007/009 ✓ made every on-device
component unused. Downstream: #012 (eval re-baseline) inherits a clean `eval/`
whose prompt import points at `hable_ya` directly; #015 (docs) rewrites the
README/OVERVIEW that still describe the on-device stack. `cuda_bootstrap.py` was
already removed in #009.

---

## What

### Acceptance Criteria

**#010 — dependencies (`pyproject.toml`, `uv.lock`):**

- [ ] `anthropic` is a **core** dependency (the runtime imports it). It is removed
  from the `eval` extra (now redundant); the `finetune` extra is deleted whole.
- [ ] `faster-whisper` and `piper-tts` are removed from core deps (no code
  imports them post-#007).
- [ ] The `finetune` optional-dependency group (`torch`, `unsloth`,
  `transformers`, `datasets`, `huggingface_hub`, `anthropic`) is deleted.
- [ ] `jupyterlab` is removed from core deps (it existed only for the fine-tune
  notebook, which #011 deletes). *(Key Decision 3 — reversible.)*
- [ ] The stale `openai` core-dep comment ("OpenAI-compatible llama.cpp
  endpoint") is corrected — `openai` is kept, now used by `OpenAISTTService`.
- [ ] `uv sync` (no extras) resolves and installs a runnable app; `uv.lock` is
  refreshed.

**#011 — tooling (code + config):**

- [ ] `finetune/` is deleted in full (`format.py`, `generate.py`, `validate.py`,
  `review/`, `datasets/`, `__init__.py`).
- [ ] The three remaining importers of `finetune.format.render_system_prompt` —
  `eval/run_eval.py`, `eval/agent/run_agent_eval.py`, `tests/test_agent_personas.py`
  — import `render_system_prompt` from `hable_ya.pipeline.prompts.render`
  (its real home; `finetune.format` only re-exported it).
- [ ] Deleted: `scripts/download_model.py`, `scripts/benchmark_concurrency.py`,
  `scripts/benchmark_latency.py`, `notebooks/gemma4_finetune.ipynb` (and the
  now-empty `notebooks/` tree, incl. any `unsloth_compiled_cache/`).
- [ ] Deleted: `scripts/replay_placement.py` — dead on-device eval (targets the
  removed llama.cpp endpoint; references the removed `settings.llama_cpp_url`).
  A cloud band-emission regression, if wanted, is #012's to design fresh.
- [ ] `pyproject` tooling config is cleaned of references to deleted paths: the
  `[tool.mypy.overrides]` `finetune.*` module entry, the `[tool.mypy]`
  `unsloth_compiled_cache` excludes, and the `[tool.ruff.lint.per-file-ignores]`
  entries for `finetune/*`, `scripts/benchmark_concurrency.py`, `notebooks/*.ipynb`.
- [ ] `models/.gitkeep` removed (the `models/` dir only held GGUF weights for the
  deleted `download_model.py` / the #009-removed llama.cpp service).

**Both:**

- [ ] `pytest` passes; `ruff check hable_ya api eval/agent tests scripts` and
  `mypy hable_ya api eval/agent` clean; CI (`uv sync --extra eval --extra dev`)
  still resolves.

### Non-Goals

- **No eval `re-baseline`** (#012). `eval/` keeps working (only the import
  source changes); rethinking it for Claude is separate.
- **No docs rewrite** (#015). README/OVERVIEW/ARCHITECTURE still describe the
  on-device stack; this slice may touch only `pyproject` comments and the code
  it deletes. (The dangling doc references are #015's to fix.)
- **No runtime behavior change.** Pure removal + dependency/config hygiene.
- **No `scripts/fixtures/` or `scripts/voice_client.py` removal** — fixture
  generation is eval tooling (kept for #012); `voice_client.py` is a dev client
  for the (cloud) WS endpoint.

### Open Questions

1. **`jupyterlab` removal.** It's a heavy core dep that existed for the fine-tune
   notebook. Recommend removing it (nothing imports it; re-addable with
   `uv add jupyterlab` for ad-hoc use). Confirm in review.

---

## How

### Approach

**Deps (#010).** Edit `pyproject.toml`: in `[project].dependencies` drop
`faster-whisper` + `piper-tts` (+ `jupyterlab`), add `anthropic>=0.40.0`, fix the
`openai` comment; in `[project.optional-dependencies]` remove `anthropic` from
`eval` and delete the whole `finetune` group. `uv sync` to refresh `uv.lock`.

**Redirect imports (#011).** In the three importers, change
`from finetune.format import render_system_prompt` →
`from hable_ya.pipeline.prompts.render import render_system_prompt`. This is
behavior-preserving — `finetune.format` imported the same symbol from that
module (verified `finetune/format.py:15-21`).

**Delete tooling (#011).** `git rm -r finetune/`; `git rm` the three scripts,
`replay_placement.py`, the notebook, and `models/.gitkeep`. Remove the matching
`pyproject` `[tool.mypy]` / `[tool.ruff]` config entries for those paths.

**Order:** redirect imports first, then delete `finetune/`, then the deps/config
— so nothing is transiently unimportable while running gates.

### Confidence

**Level:** High

**Rationale:** The coupling is fully mapped. `finetune.format` is only a
re-export used by exactly three files (plus the `benchmark_concurrency.py` being
deleted); `fixture_to_sft` and `finetune.{generate,validate,review}` have zero
external importers (grep-verified). No runtime code imports `faster-whisper`,
`piper-tts`, `torch`, `unsloth`, or `transformers`. The only real risk is a
missed transitive import, which the gates catch immediately.

**Validate before proceeding:** none required (High). The two proofs are in the
gates: a clean `uv sync` with no `finetune` extra installs a runnable app, and
`pytest` stays green after the `finetune/` deletion.

### Key Decisions

1. **Redirect the prompt import to `hable_ya`, then delete `finetune/` whole.**
   `render_system_prompt` lives in `hable_ya.pipeline.prompts.render`;
   `finetune.format` was a passthrough. Pointing importers at the source lets the
   package go entirely, rather than keeping a stub `format.py`.
2. **Promote `anthropic` to core (fixes a real bug).** The runtime imports it;
   having it only in extras means `uv sync` yields a broken app. Remove the now-
   redundant copy from the `eval` extra.
3. **Remove `jupyterlab`** (Open Question 1) — notebook-only, heavy, re-addable.
4. **Remove `replay_placement.py` here.** It's on-device eval tooling (llama.cpp)
   and is already broken against the removed `llama_cpp_url`; #011's charter is
   "remove on-device tooling," so it fits. Any cloud regression harness is #012.
5. **Bundle #010 + #011.** The deps and the code that pulls them must move
   together to avoid an inconsistent half-state.

### Testing Approach

Removal-heavy; the suite plus a clean-install check is the coverage:

- **`tests/test_agent_personas.py`:** already imports `render_system_prompt`
  (now from `hable_ya`); it must stay green — the direct proof the redirect is
  behavior-preserving.
- **Full `pytest`:** green after `finetune/` deletion (no test imports the
  deleted training code; grep-confirmed).
- **Clean install:** `uv sync` (no extras) succeeds and `python -c "import
  api.main"` imports — proves `anthropic`-in-core and that nothing runtime needs
  a removed dep.
- **Gates:** `ruff check hable_ya api eval/agent tests scripts` and `mypy
  hable_ya api eval/agent` clean (the CI targets); CI's `uv sync --extra eval
  --extra dev` still resolves.
- No new test files needed — this slice deletes, it doesn't add behavior.
