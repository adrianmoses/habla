# habla

A voice-first Spanish language-acquisition agent. Claude acts simultaneously as
the conversational partner, pedagogical assessor, and adaptive engine. The
runtime is a Pipecat STT → LLM → TTS pipeline exposed as a FastAPI WebSocket,
with a knowledge-graph learner model (Postgres + Apache AGE) updated via native
tool calls.

`habla` is the cloud-API fork of [`hable-ya`](https://github.com/adrianmoses/hable-ya):
same product, but the three on-device models are replaced with managed APIs.

| Role | hable-ya (on-device) | habla (cloud) |
|---|---|---|
| LLM | fine-tuned Gemma 4 E4B via llama.cpp | **Claude** (`claude-sonnet-4-6`, Pipecat `AnthropicLLMService`) |
| STT | faster-whisper (CUDA) | **OpenAI transcription** (`gpt-4o-transcribe`) |
| TTS | Piper | **Cartesia** (`sonic-3`) |

Silero VAD + SmartTurn v3 (small local CPU/ONNX models) are unchanged and stay
in-process. The runtime is CPU-only — no GPU required.

Based on ideas from `comprende-ya` and `habla.practice`.

## Design docs

Product, architecture, and roadmap live under [`docs/specs/`](docs/specs/):

- [`OVERVIEW.md`](docs/specs/OVERVIEW.md) — product summary, target consumer, non-goals, tech stack
- [`ARCHITECTURE.md`](docs/specs/ARCHITECTURE.md) — component map, data flow, constraints
- [`ROADMAP.md`](docs/specs/ROADMAP.md) — feature list and status
- [`habla_fixture_spec.md`](habla_fixture_spec.md) — authoritative fixture specification

## Setup

Requires Python ≥3.12, `uv`, Docker, and three managed-API keys:

- `ANTHROPIC_API_KEY` — Claude (LLM) and the eval judges.
- `OPENAI_API_KEY` — transcription (STT).
- `CARTESIA_API_KEY` + `CARTESIA_VOICE_ID` — speech synthesis (TTS). The voice id
  is owner-supplied and has no default; the runtime fails fast if it is unset.

The `/ws/session` endpoint is gated by a shared-secret token
(`HABLE_YA_SESSION_AUTH_TOKEN`) and is **fail-closed** — if the token is unset,
the endpoint refuses every connection. Generate a URL-safe random secret:

```bash
openssl rand -hex 32
# or: python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in `.env` as `HABLE_YA_SESSION_AUTH_TOKEN=…`, and pass it from the client
(`voice_client.py --token …`). For local dev you can bypass auth with
`HABLE_YA_SESSION_AUTH_DISABLED=true` — never in production. The token crosses
the wire in cleartext until a TLS/`wss://` reverse proxy is in front, so don't
expose the raw `ws://` port publicly without one.

```bash
uv sync
cp .env.example .env   # then fill in the three keys + CARTESIA_VOICE_ID + the auth token
```

The `eval` extra (Opus judges, spaCy recast scoring) is optional:
`uv sync --extra eval`.

## Usage

### Run

```bash
docker compose up
```

Brings up the FastAPI `app` (WebSocket on `:8000`) and the Postgres + Apache AGE
`db` service. The app reads its keys from `.env`.

To run the app on the host instead of in-compose (db still in Docker):

```bash
docker compose up -d db     # start Postgres+AGE FIRST — see note below
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The app runs Alembic migrations and opens the DB pool **during startup**, before
it serves — so the `db` service must be up first. If Postgres is unreachable the
lifespan raises and uvicorn exits (it won't sit and retry indefinitely). A
successful boot ends with `hable-ya ready on 0.0.0.0:8000`; watch for that line.
(When redirecting output to a file/pipe, later startup logs may buffer and lag —
probe `GET /health` for the real readiness signal.)

### Generate eval fixtures

Requires `ANTHROPIC_API_KEY` (fixtures are generated via the Anthropic Batches API).

```bash
# Full pipeline: generate → validate → review → consolidate
python scripts/generate_eval_fixtures.py all

# Individual stages
python scripts/generate_eval_fixtures.py generate
python scripts/generate_eval_fixtures.py validate
python scripts/generate_eval_fixtures.py review
python scripts/generate_eval_fixtures.py consolidate
```

### Run model eval

Scores Claude against the fixture conversations on the pedagogical and
tool-fidelity dimensions. Requires `ANTHROPIC_API_KEY`; no local model server.

```bash
python -m eval.run_eval --output results.json

# A specific model or category subset
python -m eval.run_eval --output results.json \
    --model claude-sonnet-4-6 --categories single_error_recast,multi_error

# Concurrency and timeout
python -m eval.run_eval --output results.json --concurrency 8 --timeout 60

# Baseline ablation: role-only prompt (no register rules / recast / tool schema),
# to measure how much the runtime prompt engineering buys.
python -m eval.run_eval --output minimal.json --minimal-prompt
```

### Compare eval runs

```bash
python -m eval.compare minimal.json full.json
```

Prints per-dimension and per-band deltas with threshold-based recommendations —
e.g. the unprompted baseline vs the full runtime prompt.

### Inspect the learner model

The db is exposed on host port `5433` (compose maps `5433:5432` to avoid colliding
with a system Postgres). Creds match `docker-compose.yml`.

```bash
PGPASSWORD=hable_ya psql -h localhost -p 5433 -U hable_ya -d hable_ya
# or, via the running container:
docker compose exec db psql -U hable_ya -d hable_ya
```

Relational tables:

```sql
-- Profile snapshot (L1 reliance, fluency, error patterns, CEFR band)
SELECT * FROM learner_profile;

-- Sessions
SELECT * FROM sessions ORDER BY started_at DESC LIMIT 5;

-- Recent turns (log_turn observations land here)
SELECT id, session_id, created_at, cefr_band, l1_reliance_score
FROM turns ORDER BY created_at DESC LIMIT 20;

-- Error patterns accumulated across sessions
SELECT * FROM error_counts ORDER BY count DESC LIMIT 20;

-- Vocabulary exposure
SELECT * FROM vocabulary_items ORDER BY last_seen_at DESC LIMIT 20;
```

Knowledge graph (Apache AGE — graph name is `learner_knowledge`):

```sql
-- List graphs in the database
SELECT name FROM ag_catalog.ag_graph;

-- AGE functions need ag_catalog on the search_path
SET search_path = ag_catalog, "$user", public;

-- Peek at nodes
SELECT * FROM cypher('learner_knowledge', $$ MATCH (n) RETURN n LIMIT 10 $$)
AS (n agtype);

-- Node counts by label
SELECT * FROM cypher('learner_knowledge', $$
  MATCH (n) RETURN label(n) AS label, count(*) AS n
$$) AS (label agtype, n agtype);
```

## analiza — offline monólogo analysis

`analiza` is a standalone CLI (spec: [`docs/specs/analiza/spec.md`](docs/specs/analiza/spec.md))
that turns a recorded Spanish monólogo into deterministic fluency metrics, DELE
B2 examiner feedback, and an Obsidian session note plus a row in a long-term
stats CSV. Design principle: **deterministic layer for trends, LLM layer for
judgment** — metrics are reproducible across months regardless of prompt or
model changes; anything requiring interpretation lives in the LLM layer.

```bash
uv sync --extra analiza
uv run python -m spacy download es_core_news_sm   # lemmas for TTR/MTLD
# ffmpeg must be on PATH; ANTHROPIC_API_KEY for the examiner pass

uv run analiza grabacion.m4a --tema "mi fin de semana"
uv run analiza grabacion.m4a --no-llm --dry-run   # metrics only, print to stdout
```

Transcription runs on the GPU when the CUDA runtime libs are present and falls
back to CPU otherwise. A ~65 s sample recording lives at
`tests/fixtures/analiza/monologo-prueba-65s.m4a`.

### The metrics

Pauses come from Silero VAD, not from the transcript — VAD is immune to
transcription errors, so it is the authoritative source for pause metrics.
Word-level data (fillers, repeats, confidence) comes from faster-whisper with
`condition_on_previous_text=False` to reduce error-correction smoothing.

**Rate & pausing** — the hesitation profile:

- `wpm_gross` — words ÷ total duration × 60. The headline speaking rate.
- `wpm_articulation` — words ÷ speech time (VAD) × 60. How fast you speak
  *while actually speaking*. A large gap between articulation and gross rate
  means the time is going into silences, not slow speech.
- `pauses_n`, `pauses_total_s`, `pause_max_s` — VAD silences ≥ 0.7 s
  (configurable), including leading/trailing silence.
- `pauses_midclause_n` — pauses whose preceding transcribed word doesn't end a
  sentence (no `.?!`). A proxy for word-retrieval struggle: pausing at a
  sentence boundary is natural, pausing mid-clause usually isn't.

**Lexical range** — the *alcance* trend:

- `connectors_unique_n` — distinct B2 discourse connectors matched from the
  inventory in `analiza/conectores_b2.py` (longest-first, word-bounded;
  discontinuous pairs like "no solo … sino también" count once).
- `connectors_formal_ratio` — formal ÷ total connectors matched. The main
  register-range trend metric.
- `ttr` — type–token ratio over spaCy lemmas. Simple but length-sensitive.
- `mtld` — Measure of Textual Lexical Diversity over lemmas. Preferred over
  TTR because it is robust to recording length; higher = more varied
  vocabulary.

**Disfluency & data quality:**

- `fillers_n`, `fillers_per_min` — muletillas ("eh", "pues", "o sea", …).
  **A floor, not truth**: Whisper suppresses fillers, so only the trend
  direction is meaningful, never the absolute value.
- `repeats_n` — immediately repeated words or two-word phrases ("para para",
  "a la a la"). A self-repair proxy.
- `low_conf_spans_n` — runs of ≥2 consecutive words transcribed with
  probability < 0.5. Passed to the examiner as "audio unclear here" hints;
  also flags mumbling.
- `vad_transcript_gap_s` — speech time (per VAD) with no transcribed words.
  Usually suppressed fillers or mumbling; a data-quality signal, not a skill
  metric.

Known limitations (spec §5): Whisper silently corrects some learner errors, so
the examiner's error table is a lower bound; pronunciation is out of scope for
v0.x; examiner scores from different `prompt_version`s are not comparable —
the stats CSV records the version so trend analysis can filter on it.

## History

This fork replaced hable-ya's on-device model stack with cloud APIs. The
fine-tuning workstream (Unsloth SFT dataset generation, the training notebook)
and the on-device serving tooling (`download_model.py`, the llama.cpp GPU compose
service, faster-whisper / piper) were removed in the migration — see
[`ROADMAP.md`](docs/specs/ROADMAP.md) #009–#012. The eval harness was re-baselined
to score Claude directly (#012); the Opus recast/session judges and the fixture
pipeline carry over unchanged.

## Development

```bash
pytest
ruff check .
mypy .
```
