# Decision Record: Cloud STT + TTS — OpenAI Whisper and Cartesia

| Field | Value |
|---|---|
| id | 007 |
| status | implemented |
| created | 2026-07-05 |
| spec | [spec.md](./spec.md) |

---

## Context

Spec 001 moved the LLM to Claude but left STT (`faster-whisper`, CUDA) and TTS
(Piper) on-device, so the app still needed a GPU just to transcribe. This slice
swaps both leaf services in `hable_ya/pipeline/services.py::load_services` for
managed APIs — the same pattern as spec 001, one level simpler (STT/TTS carry no
tool-calling or context semantics). Both constructors were verified against the
installed `pipecat-ai 0.0.108` before writing code. It was implemented on branch
`spec-stt-tts-cloud-007-008` (the first slice to use branch-per-spec + PR, vs.
spec 001 landing directly on `main`).

Two things shaped the work beyond the spec: the owner had already placed
`OPENAI_API_KEY`, `CARTESIA_API_KEY`, and `CARTESIA_VOICE_ID` in `.env`, so the
config fields alias those exact names; and building the live smoke surfaced two
non-obvious facts about pipecat's STT (below).

## Decision

STT is **OpenAI `gpt-4o-transcribe`** via `OpenAISTTService`; TTS is **Cartesia
`sonic-3`** via the streaming websocket `CartesiaTTSService`. Both take
`language=Language.ES`; the Cartesia voice is an owner-supplied `voice_id`. Keys
and voice come from the standard `OPENAI_API_KEY` / `CARTESIA_API_KEY` /
`CARTESIA_VOICE_ID` env names (validation-aliased, matching spec 001's
`anthropic_api_key`). The `whisper_*` / `piper_*` config fields are removed; the
`cartesia` package is added (`openai` was already a core dep). The pipeline slots
and downstream consumers are unchanged — `runner.py` / `session.py` were not
touched. After this slice the model path is CPU-only (only Silero VAD +
SmartTurn ONNX remain local), which unblocks the GPU-free deploy (#009).

---

## Alternatives Considered

### STT model

**Option A — `gpt-4o-transcribe` (chosen).** OpenAI's current transcription
model, the Pipecat default.
- Pros: materially stronger on Spanish — the exact axis hable-ya #047 found
  `faster-whisper medium` weak on; verified live (exact round-trip transcript).
- Cons: pricier per minute than `whisper-1`.

**Option B — `whisper-1`** (the literal "Whisper" the roadmap named), or
**`gpt-4o-mini-transcribe`**.
- Pros: cheaper.
- Cons: lower Spanish accuracy; the roadmap's "Whisper" wording is about the API
  family, not a specific checkpoint.

**Chosen: A**, configurable via `stt_model` so B remains a one-line fallback
after a cost call.

### Smoke-test design

**Option A — TTS→STT round-trip (chosen).** Synthesize a Spanish sentence with
Cartesia, feed that audio to OpenAI STT, assert a non-empty (ideally matching)
transcript.
- Pros: self-contained — no bundled audio asset; exercises *both* services and
  both credentials + the voice in one run.
- Cons: couples the two; a format mismatch could fail STT even if TTS is fine
  (mitigated — see below).

**Option B — independent checks** (TTS asserts non-empty audio; STT transcribes
a bundled Spanish WAV).
- Cons: needs a committed audio fixture; more moving parts.

**Chosen: A.** The round-trip returned the sentence verbatim.

### GPU / `cuda_bootstrap`

**Keep it, scope this slice to the service swap (chosen).** After the swap the
runtime path needs no CUDA, but removing `bootstrap_cuda` (`api/main.py`), the
Docker GPU reservation, and the llama.cpp compose service is deploy-shaped work
with its own testing — that's #009. `bootstrap_cuda` is harmless to leave (it
only sets library paths at import). Pulling the one-line removal in was offered
and declined in favor of a clean, single-purpose slice.

### Dependencies

**Add `cartesia` only (chosen); defer removing `faster-whisper`/`piper-tts` to
#010.** The runtime now hard-depends on `cartesia`, so it's added here; the
now-unused local deps are removed alongside the `anthropic`/`cartesia` promotion
in the #010 cleanup — consistent with how spec 001 left dep churn to #010.

---

## Tradeoffs

- **Per-minute STT + per-character TTS cost** replaces free local inference.
- **Added network hops** — cloud STT (per-utterance HTTP) and TTS (streaming
  websocket) add latency to the turn; measuring/tuning is #013.
- **Owner-supplied voice** — `cartesia_voice_id` has no safe default; the runtime
  logs `<unset>` and the smoke fails fast if it's missing.
- **Deprecated constructor form** — `OpenAISTTService(model=…)` /
  `CartesiaTTSService(model=…, params=…)` emit `DeprecationWarning`s in 0.0.108
  (favoring `settings=…Settings(…)`), the same style spec 001 used for the LLM.
  Kept for consistency; a future cleanup can migrate all three services to
  `settings=` at once.
- **`.env` not auto-loaded by the app** — see Spec Gaps.

---

### Spec Divergence

The implementation matched the spec. No material divergences; two
implementation details worth recording (neither changes the spec's intent):

| Spec Said | What Was Built | Reason |
|---|---|---|
| `cartesia_voice_id` is an owner-supplied config value | Aliased to the `CARTESIA_VOICE_ID` env name | The owner had already set that exact name in `.env`. |
| Smoke feeds TTS audio into STT | Smoke wraps the PCM as WAV and promotes the STT sample rate before `run_stt` | `run_stt`/`_transcribe` expect WAV and a non-zero sample rate; in-pipeline the segmented STT does both, but a standalone caller must (see Spec Gaps). |

---

## Spec Gaps Exposed

- **The running app never loads `.env`.** `Settings` reads OS env only
  (`model_config` has no `env_file`), so the keys reach a `uvicorn`-launched app
  only if exported. This affects spec 001's `anthropic_api_key` identically. The
  smoke/spike work around it with `load_dotenv()`. Candidate fix: add
  `env_file=".env"` to `Settings.model_config` — a one-liner, best folded into
  #009 (deploy) or a tiny standalone follow-up.
- **`OpenAISTTService.run_stt` has undocumented preconditions for standalone
  use** — it expects WAV bytes and a sample rate set via the pipeline
  `StartFrame` (`stt_service.py:286`); called directly it silently transcribes
  at rate 0 and returns empty (errors are swallowed into an `ErrorFrame`).
  Relevant to any future code (eval, tooling) that drives STT outside the
  pipeline; captured in `scripts/smoke_stt_tts.py`.
- **All three services use the deprecated `model=`/`params=` constructor form.**
  A future slice could migrate STT/TTS/LLM to the non-deprecated `settings=…`
  form together.

---

## Test Evidence

Offline gates:

```
$ uv run pytest -q
248 passed, 52 skipped, 9 warnings in 12.52s

$ uv run ruff check hable_ya api tests scripts
All checks passed!

$ uv run mypy hable_ya api
Success: no issues found in 45 source files
```

Live smoke (`scripts/smoke_stt_tts.py`, real OpenAI + Cartesia APIs):

```
Synthesizing (Cartesia sonic-3): 'Hola, me llamo Ana y hoy fui a la tienda.'
  -> 99282 bytes of PCM
Transcribing (OpenAI gpt-4o-transcribe) ...
  -> 'Hola, me llamo Ana y hoy fui a la tienda.'

PASS — cloud STT + TTS both live
```

The transcript is byte-identical to the synthesized sentence — proof that the
Cartesia key + voice + `sonic-3` and the OpenAI key + `gpt-4o-transcribe` all
work end to end.
