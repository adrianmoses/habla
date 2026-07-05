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
| 001 | Claude LLM via Pipecat `AnthropicLLMService`, replacing the llama.cpp `OpenAILLMService` (drop `base_url`/dummy `api_key`) | planned | — |
| 002 | Register `HABLE_YA_TOOLS` with the LLM context + force emission with `tool_choice` — switch `log_turn` from plain-text contract to native structured tool-calling | planned | — |
| 003 | Rework the tool handler to consume native function-call frames instead of buffering `LLMTextFrame`s and regex-parsing `log_turn(...)` / `[TOOL_CALL: log_turn]{...}` (reuse the existing `api_tool_calls` path in `parse_tool_calls`) | planned | — |
| 004 | System prompt: move the `log_turn` emission instruction into the tool definition; remove the inline plain-text-emission contract the fine-tune baked in | planned | — |
| 005 | Config: Anthropic model id + `ANTHROPIC_API_KEY`; remove `llama_cpp_url`, `llm_model_name`, and the Gemma `chat_template_kwargs.enable_thinking=false` hack | planned | — |
| 006 | Replace the llama.cpp warmup ping-loop with a lightweight managed-API health check (or drop it) | planned | — |
| 007 | STT → OpenAI Whisper API (replace faster-whisper CUDA `medium`); Spanish language config | planned | — |
| 008 | TTS → Cartesia (replace Piper `es_ES-davefx-medium`); select a Spanish voice | planned | — |
| 009 | Deployment: delete the llama.cpp GPU compose service and drop all `nvidia` GPU reservations — app container becomes CPU-only (Postgres + AGE `db` service unchanged) | planned | — |
| 010 | Dependency cleanup: drop `faster-whisper`, `piper-tts`, and the `finetune` extra (`torch`, `unsloth`, `transformers`); promote `anthropic` to core; add Pipecat anthropic / whisper / cartesia service extras | planned | — |
| 011 | Remove on-device-only tooling: `cuda_bootstrap.py`, `download_model.py`, `benchmark_*` scripts, the `finetune/` package, and the fine-tune notebook | planned | — |
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
