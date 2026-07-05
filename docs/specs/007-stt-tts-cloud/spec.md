# Spec: Cloud STT + TTS — OpenAI Whisper and Cartesia

| Field | Value |
|---|---|
| id | 007 |
| status | draft |
| created | 2026-07-05 |
| covers roadmap | #007, #008 (bundle) |

---

## Why

Spec 001 moved the LLM to Claude but left the two other on-device models in
place: STT is `faster-whisper` (`WhisperSTTService`, CUDA) and TTS is Piper
(`PiperTTSService`), both constructed in `hable_ya/pipeline/services.py`. As
long as `faster-whisper` runs in-process the app **still needs a GPU**, which
largely defeats the point of a cloud fork — a truly serverless deploy can't
require an NVIDIA box just for transcription. This slice swaps both for managed
APIs: **STT → OpenAI's transcription API** and **TTS → Cartesia**.

It's the same "replace a local Pipecat service with a cloud one" shape as the
LLM swap, so #007 and #008 bundle: they share the config/keys/deps churn and
the same live-smoke validation, and splitting them would ship a half-cloud
runtime (still GPU-bound on whisper) with no product benefit.

### Consumer Impact

- **End user (learner):** Same voice loop — they speak, they hear a Spanish
  reply. Two concrete quality/latency shifts: (1) transcription moves off the
  `faster-whisper medium` quality ceiling that hable-ya #047 hit for Spanish to
  OpenAI's `gpt-4o-transcribe`, which should improve recognition of learner
  Spanish (and their English fallbacks, which the `log_turn.L1_used` signal
  depends on); (2) STT and TTS now add network round-trips to the turn.
- **Project owner:** The app becomes **CPU-only** on the model path — no GPU
  needed for the STT/TTS/LLM loop (only the small local Silero VAD + SmartTurn
  ONNX models remain, and those run on CPU). This unblocks the GPU-free deploy
  (#009). New per-minute STT and per-character TTS costs replace free local
  inference.
- **Downstream:** The learner model, `log_turn` handling, prompt, and pipeline
  shape are unchanged — STT/TTS are leaf services swapped in the same pipeline
  slots.

### Roadmap Fit

Bundles #007 (OpenAI Whisper STT) + #008 (Cartesia TTS). Upstream: spec 001
(Claude LLM) ✓ established the cloud-service + API-key pattern this reuses.
Downstream unblocked: #009 (drop the llama.cpp GPU compose service and GPU
reservation — after this slice nothing in the runtime path needs CUDA), #013
(latency re-benchmark, which must account for the new STT/TTS hops). Dependency
cleanup that removes the now-unused `faster-whisper`/`piper-tts` and promotes
`anthropic`/`cartesia` in `pyproject` is #010.

---

## What

### Provider decisions (settled here, confirm in review)

- **STT model:** `gpt-4o-transcribe` (OpenAI's current transcription model, the
  Pipecat default) — recommended over the literal `whisper-1` for materially
  better non-English/Spanish accuracy, which is the exact axis hable-ya #047
  found `faster-whisper medium` weak on. Configurable; `whisper-1` /
  `gpt-4o-mini-transcribe` are cheaper fallbacks. Both run through the same
  `OpenAISTTService`. (Key Decision 1.)
- **TTS model:** Cartesia `sonic-3` (Pipecat default) over the streaming
  `CartesiaTTSService` (websocket, low time-to-first-byte — right for voice).
- **Voice:** a Cartesia Spanish `voice_id` is required; it has no sensible
  hardcoded default, so it's a config value the owner supplies (Open Question 1),
  the same way `piper_voice` was.

### Acceptance Criteria

With `OPENAI_API_KEY` and `CARTESIA_API_KEY` set and a Cartesia Spanish
`voice_id` configured:

- [ ] `hable_ya/pipeline/services.py::load_services` constructs an
  `OpenAISTTService` (model from config, `language=Language.ES`, `api_key` from
  config) in place of `WhisperSTTService`, and a `CartesiaTTSService`
  (`voice_id` + model from config, `api_key` from config, `sample_rate =
  settings.audio_sample_rate`, Spanish language) in place of `PiperTTSService`.
- [ ] The `Services` dataclass field types are updated to the new service
  classes; `runner.py`'s pipeline still places `services.stt` and `services.tts`
  in the same slots (STT after the turn observer, TTS after the LLM/emission
  observer) — no topology change.
- [ ] `hable_ya/config.py`: adds `openai_api_key` (reads standard
  `OPENAI_API_KEY`), `cartesia_api_key` (`CARTESIA_API_KEY`), `stt_model`
  (default `gpt-4o-transcribe`), `cartesia_voice_id`, and `cartesia_model`
  (default `sonic-3`). Removes the faster-whisper-specific `whisper_model`,
  `whisper_device`, `whisper_compute_type` and the Piper `piper_voice`,
  `piper_model_dir`. Every reference to the removed fields is updated or deleted.
- [ ] The `cartesia` package is added as a dependency and installs cleanly
  (`openai` is already a core dep, so STT needs no new package).
- [ ] A live smoke test transcribes a short Spanish audio clip via
  `OpenAISTTService` and synthesizes a short Spanish sentence via
  `CartesiaTTSService` — proving both credentials, the model ids, and the voice
  id work end to end (analogous to spec 001's spike).
- [ ] `pytest` passes (config assertions updated for the new fields; structural
  pipeline test still green); ruff + mypy clean.

### Non-Goals

- **No GPU / deploy cleanup.** Removing `bootstrap_cuda` (`api/main.py`), the
  Docker `nvidia` GPU reservation, and the llama.cpp compose service is #009.
  This slice makes the runtime *not need* a GPU; it doesn't rip out the GPU
  plumbing (Key Decision 3).
- **No dependency removal.** `faster-whisper` and `piper-tts` stay in
  `pyproject` (now unused) for #010 to remove alongside promoting
  `anthropic`/`cartesia`. This slice only *adds* `cartesia` (the runtime now
  hard-depends on it).
- **No latency re-benchmark (#013).** The new hops are noted; measuring/tuning
  `smart_turn_stop_secs` / VAD for them is its own slice.
- **No STT prompt-priming tuning.** `OpenAISTTService` accepts a `prompt` for
  domain priming (the lever hable-ya #047 explored); wiring/tuning it is
  deferred — default `prompt=None`.
- **No VAD/turn-detection change.** Silero VAD + SmartTurn v3 stay local (small
  CPU ONNX); they are not "on-device models" in the cloud-migration sense.

### Open Questions

1. **Cartesia Spanish `voice_id`.** Needs a real value from the owner's Cartesia
   account (a `sonic` Spanish voice). Recommend: ship a `cartesia_voice_id`
   config field with a documented placeholder and require it be set (fail fast
   in the smoke test), like `piper_voice` was owner-chosen. Resolve with owner.
2. **STT model default** — `gpt-4o-transcribe` (recommended, quality) vs
   `whisper-1` (cheaper, literal "Whisper"). One-line config default; resolve
   after the smoke test / a cost call.

---

## How

### Approach

**Services (`hable_ya/pipeline/services.py`).** In `load_services`, replace the
`WhisperSTTService(...)` block with:

```python
stt = OpenAISTTService(
    api_key=settings.openai_api_key,
    model=settings.stt_model,
    language=Language.ES,
)
```

and the `PiperTTSService(...)` block with:

```python
tts = CartesiaTTSService(
    api_key=settings.cartesia_api_key,
    voice_id=settings.cartesia_voice_id,
    model=settings.cartesia_model,
    sample_rate=settings.audio_sample_rate,
    params=CartesiaTTSService.InputParams(language=Language.ES),
)
```

Update the `Services` dataclass field types (`stt: OpenAISTTService`,
`tts: CartesiaTTSService`) and the imports. `runner.py` and `session.py` are
untouched — they reference `services.stt` / `services.tts` abstractly.

**Config (`hable_ya/config.py`).** Add `openai_api_key` /`cartesia_api_key`
(validation-aliased to the standard `OPENAI_API_KEY` / `CARTESIA_API_KEY`, same
pattern as `anthropic_api_key`), `stt_model`, `cartesia_voice_id`,
`cartesia_model`. Remove the five whisper/piper fields.

**Deps.** Add `cartesia` to `pyproject` core dependencies; `uv sync`.

**Smoke test (`scripts/smoke_stt_tts.py`, throwaway).** Mirror spec 001's spike:
construct `OpenAISTTService` and transcribe a short bundled/synth Spanish clip;
construct `CartesiaTTSService` and synthesize a short Spanish sentence to bytes.
Assert non-empty transcript text and non-empty audio, and that the configured
`voice_id`/models are accepted. Needs both keys + the voice id.

### Confidence

**Level:** High

**Rationale:** This is the exact swap pattern spec 001 proved, one level simpler
— STT/TTS are leaf services with no tool-calling or context semantics. Both
constructors are verified against the installed `pipecat-ai 0.0.108`
(`services/openai/stt.py`, `services/cartesia/tts.py`); `OpenAISTTService`
buffers a VAD-gated utterance and transcribes (same contract as the current
`WhisperSTTService`), and `CartesiaTTSService` is a streaming websocket TTS. The
pipeline slots and downstream consumers don't change. The only unknowns are
*values*, not mechanism: the Cartesia Spanish `voice_id` and that both API keys
work — exactly what the smoke test checks.

**Validate before proceeding:**

1. Owner provides a Cartesia Spanish `voice_id` + `CARTESIA_API_KEY` and an
   `OPENAI_API_KEY` (Open Question 1).
2. Run the smoke test to confirm both services accept the configured
   models/voice and return non-empty results before wiring is called done.

### Key Decisions

1. **`gpt-4o-transcribe`, not `whisper-1`.** The roadmap says "Whisper," but
   OpenAI's modern transcription endpoint is `gpt-4o-transcribe`, which is
   stronger on Spanish — directly addressing the `faster-whisper medium` ceiling
   hable-ya #047 documented. Same `OpenAISTTService`, one config value; the
   cheaper `whisper-1`/`gpt-4o-mini-transcribe` remain available.
2. **Cartesia streaming `sonic-3`.** The websocket `CartesiaTTSService` gives low
   time-to-first-byte, which matters most for perceived voice latency; `sonic-3`
   is the current default. Voice is owner-supplied (no safe default).
3. **Keep GPU plumbing; scope this to the service swap.** After this slice the
   runtime path needs no CUDA, but removing `bootstrap_cuda`, the Docker GPU
   reservation, and the llama.cpp compose service is #009 — it's deploy-shaped,
   entangled with the compose file, and warrants its own testing. Bundling it
   here would creep scope. `bootstrap_cuda` is harmless to leave (it only sets
   library paths at import). *If the owner prefers, pulling the one-line
   `bootstrap_cuda` removal into this slice is low-risk — flagged, not assumed.*
4. **Add `cartesia`, defer removing `faster-whisper`/`piper-tts`.** The runtime
   now hard-depends on `cartesia` (add it); the now-unused local deps are
   removed in the #010 cleanup, consistent with how spec 001 left `anthropic`
   promotion to #010.

### Testing Approach

Per the project's pytest suite, plus a live smoke (STT/TTS need real services,
so unit-testing the live path isn't meaningful — mirror spec 001's spike/offline
split):

- **`tests/test_config.py`:** assert the whisper/piper fields are gone and
  `openai_api_key` / `cartesia_api_key` / `stt_model` (`gpt-4o-transcribe`) /
  `cartesia_voice_id` / `cartesia_model` (`sonic-3`) exist; `openai_api_key`
  reads `OPENAI_API_KEY` and `cartesia_api_key` reads `CARTESIA_API_KEY`.
- **`tests/test_runner.py`:** unchanged — the structural pipeline-order test
  still passes (STT/TTS occupy the same slots); confirm no regression.
- **Live smoke (`scripts/smoke_stt_tts.py`, human-run):** with both keys + the
  Spanish `voice_id`: transcribe a short Spanish clip (assert non-empty,
  plausibly-correct text) and synthesize a short Spanish sentence (assert
  non-empty audio). This is the analog of spec 001's spike and the gate before
  calling the slice done.
- **Manual end-to-end (human-run, optional):** a short live session confirming
  the full STT→LLM→TTS loop speaks and hears Spanish — overlaps with #013's
  latency read.
