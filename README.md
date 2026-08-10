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

The La Libreta handoff (spec #033) has its **own** secret, `LA_LIBRETA_API_TOKEN`,
which authorizes `POST /api/sessions` and the outbound completion callback. It is
not interchangeable with the session token: holding it lets La Libreta create a
speaking handoff and nothing else — not a microphone, not a provider socket, not
a learner's progress. Running the integration also needs
`HABLE_YA_PUBLIC_BASE_URL` (the canonical origin the returned deep link is built
from) and, for callbacks, `HABLE_YA_LA_LIBRETA_CALLBACK_ORIGINS` — a
comma-separated HTTPS origin allowlist that is **empty by default**, so no
callback destination is permitted until you name one. Startup refuses to boot if
the token or the base URL is missing; set
`HABLE_YA_LA_LIBRETA_INTEGRATION_DISABLED=true` to run without the integration
(the base `docker-compose.yml` does exactly that).

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
SELECT id, session_id, timestamp, cefr_band, fluency_signal, l1_used
FROM turns ORDER BY timestamp DESC LIMIT 20;

-- Error patterns accumulated across sessions
SELECT * FROM error_counts ORDER BY count DESC LIMIT 20;

-- Vocabulary exposure
SELECT * FROM vocabulary_items ORDER BY last_seen_at DESC LIMIT 20;
```

Knowledge graph (Apache AGE — graph name is `learner_knowledge`). It is written
every turn but **read by nothing that adapts** — every adaptive decision comes
from the relational tables above. Treat it as an inspection artifact; spec #022
records why, and `GET /dev/learner` returns a `graph` block with the same counts
these queries produce.

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
# The Spanish spaCy model (lemmas for TTR/MTLD) is a declared dependency —
# it arrives with the sync, no `spacy download` step needed.
# ffmpeg must be on PATH; ANTHROPIC_API_KEY for the examiner pass

uv run analiza sesion grabacion.m4a --tema "mi fin de semana"
uv run analiza sesion grabacion.m4a --no-llm --dry-run  # metrics only, to stdout
uv run analiza progreso --desde 2026-06-01              # read across sessions
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

### Progress across sessions

`analiza progreso` reads the stats CSV and the stored `examiner.json` files —
no audio, no re-transcription — and reports which error patterns keep coming
back and which metrics moved. Recurrence is tracked by `pattern_id`, a curated
vocabulary in `analiza/patrones_b2.py`, because the examiner's free-text
`patron` prose is not stable enough to match a fault on across two runs of the
same recording (spec [034](docs/specs/034-analiza-progreso/spec.md) §Why).

Most of what the command does is decline to conclude things. Trends compare a
first window against a last window instead of fitting a line; sessions are
segmented by `(prompt_version, whisper_model)` so a trend never spans a change
that redefined what it measures; a pattern's absence counts as evidence only
when the session could have reported it and didn't; and below eight sessions
(configurable) it writes the numbers and declines the story.

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
pytest              # unit + DB suite (DB tests skip if Postgres is down)
ruff check .
mypy .

cd web && npm test  # pure client-side logic (vitest)
```

### Browser checks

A handful of things can only be verified in a real browser — rendered layout,
and whether a name saved in Ajustes reaches Home without a reload. Spec #021
shipped a defect in exactly that gap (a 40-character name wrapped the greeting
to five lines and pushed the CTA off screen) while every unit test passed, so
those live in `tests/e2e/` and run in CI.

They are deselected from a normal `pytest` run, because they need three extra
things:

```bash
uv sync --extra dev --extra e2e
uv run playwright install chromium
cd web && npm run build          # the tests serve web/dist themselves

uv run pytest tests/e2e -m e2e
```

Missing any of those skips with a reason rather than failing. CI sets
`HABLE_YA_E2E_REQUIRED=1`, which turns those skips into failures — a green
check that silently ran nothing is worse than a red one.
