# Roadmap

Cloud-API fork of [`hable-ya`](https://github.com/adrianmoses/hable-ya). Same
product — a voice-first Spanish acquisition agent that is simultaneously
conversational partner, pedagogical assessor, and adaptive engine — but the
three on-device models are replaced with managed APIs:

| Role | hable-ya (on-device) | habla (cloud) |
|---|---|---|
| LLM | fine-tuned Gemma 4 E4B via llama.cpp | **Claude** (Pipecat `AnthropicLLMService`) |
| STT | faster-whisper (CUDA) | **OpenAI Whisper API** |
| TTS | Piper | **Cartesia** |

Unchanged from hable-ya: Silero VAD + SmartTurn v3 (small local CPU/ONNX
models, kept in-process), the Pipecat pipeline shape, the Postgres + Apache AGE
learner model, and the learner-profile / theming / leveling logic. The
migration is scoped to the model boundary and its fallout.

| Field | Value |
|---|---|
| status | planned |
| created | 2026-07-05 |

## Features

| ID | Feature | Status | Spec |
|---|---|---|---|
| 001 | Claude LLM (`claude-sonnet-4-6`) via Pipecat `AnthropicLLMService`, replacing the llama.cpp `OpenAILLMService` (drop `base_url`/dummy `api_key`) | implemented | [001-cloud-llm-native-tools](001-cloud-llm-native-tools/spec.md) ([decision](001-cloud-llm-native-tools/decision.md)) |
| 002 | Register `HABLE_YA_TOOLS` with the LLM context and emit `log_turn` via native structured tool-calling with `tool_choice: auto` (forcing suppresses the spoken reply — see spec Key Decision 3) | implemented | [001-cloud-llm-native-tools](001-cloud-llm-native-tools/spec.md) ([decision](001-cloud-llm-native-tools/decision.md)) |
| 003 | Rework the tool handler to consume native function-call frames instead of buffering `LLMTextFrame`s and regex-parsing `log_turn(...)` / `[TOOL_CALL: log_turn]{...}` (reuse the existing `api_tool_calls` path in `parse_tool_calls`) | implemented | [001-cloud-llm-native-tools](001-cloud-llm-native-tools/spec.md) ([decision](001-cloud-llm-native-tools/decision.md)) |
| 004 | System prompt: move the `log_turn` emission instruction into the tool definition; remove the inline plain-text-emission contract the fine-tune baked in | implemented | [001-cloud-llm-native-tools](001-cloud-llm-native-tools/spec.md) ([decision](001-cloud-llm-native-tools/decision.md)) |
| 005 | Config: Anthropic model id + `ANTHROPIC_API_KEY`; remove `llama_cpp_url`, `llm_model_name`, and the Gemma `chat_template_kwargs.enable_thinking=false` hack (disable thinking / low effort for voice latency) | implemented | [001-cloud-llm-native-tools](001-cloud-llm-native-tools/spec.md) ([decision](001-cloud-llm-native-tools/decision.md)) |
| 006 | Replace the llama.cpp warmup ping-loop with a lightweight managed-API health check (or drop it) | implemented | [001-cloud-llm-native-tools](001-cloud-llm-native-tools/spec.md) ([decision](001-cloud-llm-native-tools/decision.md)) |
| 007 | STT → OpenAI transcription API (`gpt-4o-transcribe`, replacing faster-whisper CUDA `medium`); Spanish language config | implemented | [007-stt-tts-cloud](007-stt-tts-cloud/spec.md) ([decision](007-stt-tts-cloud/decision.md)) |
| 008 | TTS → Cartesia (`sonic-3`, replacing Piper `es_ES-davefx-medium`); owner-supplied Spanish voice | implemented | [007-stt-tts-cloud](007-stt-tts-cloud/spec.md) ([decision](007-stt-tts-cloud/decision.md)) |
| 009 | Deployment: delete the llama.cpp GPU compose service and drop all `nvidia` GPU reservations — app container becomes CPU-only (Postgres + AGE `db` service unchanged); also removes `cuda_bootstrap.py` and loads `.env` via python-dotenv | implemented | [009-gpu-free-deploy](009-gpu-free-deploy/spec.md) ([decision](009-gpu-free-deploy/decision.md)) |
| 010 | Dependency cleanup: drop `faster-whisper`, `piper-tts`, the `finetune` extra (`torch`, `unsloth`, `transformers`), and `jupyterlab`; promote `anthropic` to core (`openai`/`cartesia` already core) | in-progress | [010-ondevice-cleanup](010-ondevice-cleanup/spec.md) |
| 011 | Remove on-device-only tooling: `finetune/` package, `download_model.py`, `benchmark_*` scripts, `replay_placement.py`, the fine-tune notebook (`cuda_bootstrap.py` removed in #009) | in-progress | [010-ondevice-cleanup](010-ondevice-cleanup/spec.md) |
| 012 | Re-baseline the `eval/` harness: validate that Claude + prompt reproduces recast + `log_turn` fidelity, replacing the fine-tuned-vs-untuned-Gemma comparator (keep the Opus recast/session judges) | planned | — |
| 013 | Cloud round-trip latency re-benchmark: measure network TTFT vs local, re-tune `smart_turn_stop_secs` / VAD `stop_secs` for the added hop | planned | — |
| 014 | API resilience & cost: rate-limit handling, retry/backoff (tenacity already present), and per-turn token-cost observability | planned | — |
| 015 | Product/docs update: on-device → cloud posture — learner utterances now leave the device (privacy), README, OVERVIEW non-goals | planned | — |

## Status Values

- `planned` — not yet started
- `in-progress` — spec written, implementation underway
- `implemented` — decision record complete
- `deprecated` — removed from product

## Revision History

| Date | Change |
|---|---|
| 2026-07-05 | Initial cloud-fork roadmap: LLM → Claude, STT → OpenAI Whisper, TTS → Cartesia. Features #001–#015 derived from the hable-ya on-device → cloud-API migration analysis. |
| 2026-07-05 | Spec 001-cloud-llm-native-tools drafted (bundles #001–#006: Claude Sonnet 4.6 via Pipecat Anthropic service, native `log_turn` tool-calling with `tool_choice: auto`, handler rework, prompt/tool-def move, config swap, warmup replacement); #001–#006 → in-progress. Corrects #002: `tool_choice` forcing suppresses the spoken reply, so emission is `auto` + prompt, not forced. Assumes a prerequisite #000 port of the hable-ya runtime into this repo. |
| 2026-07-05 | #000: hable-ya runtime ported into this repo as the baseline (git-tracked files at HEAD; hable-ya's ROADMAP and historical spec dirs excluded). |
| 2026-07-05 | Spec 010-ondevice-cleanup drafted on branch `spec-ondevice-cleanup-010-011` (bundles #010 + #011): drop `faster-whisper`/`piper-tts`/`jupyterlab` + the `finetune` extra from `pyproject`, promote `anthropic` to core (fixes a real bug — the runtime imports it but it was only in extras); delete the `finetune/` package (redirect its 3 `render_system_prompt` importers to `hable_ya.pipeline.prompts.render`, its real home), `download_model.py`, `benchmark_*`, `replay_placement.py`, and the fine-tune notebook; clean the matching mypy/ruff config. Coupling fully grep-mapped; Confidence High. #010 + #011 → in-progress. |
| 2026-07-05 | Spec 009-gpu-free-deploy implemented; #009 → implemented. Removed the llama.cpp GPU compose service + `app` nvidia reservation + `depends_on:llama`; dropped `bootstrap_cuda()` from `api/main.py` and deleted `hable_ya/cuda_bootstrap.py`; `config.py` now `load_dotenv()`s at import (`override=False`). Runtime is CPU-only end to end. Matched spec exactly (no divergences); closed the `.env`-loading gap from specs 001/007. `docker compose config` parses; 254 pytest passing; ruff + mypy clean. Dockerfile already CPU-slim (no change); dep pruning stays #010. |
| 2026-07-05 | Spec 009-gpu-free-deploy drafted on branch `spec-gpu-free-deploy-009` (#009 + the `.env`-loading gap from specs 001/007): delete the llama.cpp GPU compose service + `nvidia` reservations, remove `cuda_bootstrap.py` + its `api/main.py` call, and load `.env` via `python-dotenv` (`load_dotenv()` in `config.py`, `override=False`). Dockerfile already CPU-slim (no change). `cuda_bootstrap.py` removal pulled forward from #011. Confidence High (deletion + one dotenv line); #009 → in-progress. |
| 2026-07-05 | Spec 007-stt-tts-cloud implemented; #007 + #008 → implemented. `load_services` now builds `OpenAISTTService` (`gpt-4o-transcribe`) + `CartesiaTTSService` (`sonic-3`); config swapped to OpenAI/Cartesia keys + voice; `cartesia` dep added. Model path is CPU-only (unblocks #009). Live smoke round-tripped Cartesia→OpenAI verbatim; 248 pytest passing; ruff + mypy clean. Gaps surfaced (decision record): the app never loads `.env` (`Settings` reads OS env only — affects the anthropic key too; add `env_file`); `OpenAISTTService.run_stt` needs WAV + a set sample rate for standalone use. GPU/cuda_bootstrap removal → #009; dep removal + promotion → #010. |
| 2026-07-05 | Spec 007-stt-tts-cloud drafted on branch `spec-stt-tts-cloud-007-008` (bundles #007 + #008: OpenAI `gpt-4o-transcribe` STT + Cartesia `sonic-3` TTS replacing faster-whisper + Piper in `load_services`; new `openai_api_key`/`cartesia_api_key`/voice config; adds the `cartesia` dep; live smoke test). Same leaf-service swap pattern as spec 001 → Confidence High; only unknowns are the Cartesia Spanish `voice_id` + keys. GPU/cuda_bootstrap removal + dep cleanup deferred to #009/#010; #007 + #008 → in-progress. |
| 2026-07-05 | Spec 001-cloud-llm-native-tools implemented; #001–#006 → implemented. Divergences (see decision record): #003 landed as a `register_function` handler + a counting-only `LogTurnEmissionObserver` (old `HableYaToolHandler` removed), not a frame-parsing processor; #002 uses Anthropic's default `auto` (pipecat 0.0.108 doesn't forward `tool_choice` anyway); #005 disables thinking but `effort` isn't exposed by `AnthropicLLMService` (deferred to #013). A live two-turn spike (`scripts/spike_anthropic_tools.py`) confirmed text+tool_use co-emission, `run_llm=False` answering the tool call, and no next-turn 400. 241 pytest passing; ruff + mypy clean. Follow-ups surfaced: promote `anthropic` to core deps (#010); Step 8 live-session emission-rate/latency measurement is human-run. |
