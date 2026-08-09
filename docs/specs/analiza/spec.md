# analiza — spec v0.1

CLI that turns a recorded Spanish monólogo/narración into (1) deterministic fluency metrics, (2) LLM examiner feedback against the DELE B2 oral rubric, and (3) a session note plus a row in a long-term stats file. The note is Obsidian-shaped and files straight into a vault when one is configured, but a vault is not required — see "Output destination" below.

Design principle: **deterministic layer for trends, LLM layer for judgment.** Metrics must be reproducible across 90 days regardless of prompt or model changes; anything requiring interpretation (grammar, coherence, scoring) lives in the LLM layer and is clearly labeled as such.

---

## 1. CLI

```
analiza AUDIO [options]

Arguments:
  AUDIO                    path to .wav/.m4a/.mp3/.ogg

Options:
  --ejercicio TEXT         monologo | narrar-dia          [default: monologo]
  --tema TEXT              topic, goes into note frontmatter
  --out PATH               plain output dir               [default: ./analiza-out]
  --vault PATH             Obsidian vault root; uses the nested vault layout
  --no-llm                 metrics only, skip examiner pass
  --model TEXT             whisper model                  [default: small]
  --llm TEXT               examiner model id              [default: from config]
  --dry-run                print note to stdout, write nothing
  --lang TEXT              force language                 [default: es]

Config: ~/.config/analiza/config.toml
  vault_path, output_dir, whisper_model, llm_provider/model/key env var name,
  connector list path, thresholds (overridable per run)
```

Exit codes: 0 ok · 1 transcription failed · 2 audio unreadable · 3 output write failed · 4 LLM failed (note still written, feedback section marked pending).

**Output destination.** The Obsidian vault is one *layout*, not a prerequisite — analiza runs with nothing configured. Precedence: `--vault` > config `vault_path` > `--out` > config `output_dir` > `./analiza-out`. A vault from either source also selects the nested `Español/` layout; every other destination is flat. Only `note.output_base` knows the difference, so the writers below it are layout-agnostic.

## 2. Pipeline

```
audio ─► [A] preprocess ─► [B] VAD ─► [C] whisper ─► [D] metrics ─► [E] LLM examiner ─► [F] outputs
                                └────────────────────────┘
                                  (VAD × transcript cross-check)
```

### A. Preprocess
- ffmpeg → 16 kHz mono WAV (whisper's native format); reject < 30 s with a warning (metrics meaningless), warn > 10 min.
- Record total duration.

### B. VAD (Silero, bundled with faster-whisper)
- Produce speech segments list: `[(start, end), ...]`.
- Derive: `speech_time`, `silence_time`, `n_silences ≥ pause_threshold`.
- VAD is the **authoritative source for pause metrics** (immune to transcription errors); word-gap pauses are computed too but only as a cross-check.

### C. Transcription (faster-whisper)
- `word_timestamps=True`, `language="es"`, `condition_on_previous_text=False` (reduces error-correction smoothing), `temperature=0`.
- Default model `small`: normalizes learner errors less than `large-v3`; accuracy is sufficient for metrics. Config-overridable — if the examiner layer needs a cleaner transcript, run `--model large-v3` and accept more smoothing.
- Persist raw JSON (segments + words + probabilities) alongside outputs — reprocessing 90 days of audio later with better logic should not require re-transcription.

### D. Metrics (pure functions over VAD + word list; module `metrics.py`)

| metric | definition | notes |
|---|---|---|
| `duration_s` | total audio length | |
| `speech_time_s` | Σ VAD speech segments | |
| `wpm_gross` | words / duration × 60 | headline number |
| `wpm_articulation` | words / speech_time × 60 | gap vs gross = hesitation profile |
| `pauses_n` | VAD silences ≥ 0.7 s (config) | |
| `pauses_total_s`, `pause_max_s` | | |
| `pauses_midclause_n` | pause not preceded by `.?!` in transcript | proxy for retrieval struggle |
| `fillers_n`, `fillers_per_min` | matches from `MULETILLAS` | **floor, not truth** — whisper suppresses fillers; label as such in outputs |
| `connectors` | matched from `conectores_b2.CONECTORES` | longest-first, span-consuming, `\b`-bounded, lowercased+accents kept; discontinuous pairs count once when both halves present |
| `connectors_unique_n`, `connectors_formal_ratio` | formal / total matched | formal ratio is the alcance trend metric |
| `ttr`, `mtld` | on spaCy `es_core_news_sm` lemmas | MTLD preferred (length-robust) |
| `repeats_n` | immediate repeated unigram/bigram | self-repair proxy |
| `low_conf_spans` | consecutive words with prob < 0.5 | fed to LLM as "audio unclear here" hints; also flags mumbling |
| `vad_transcript_gap_s` | VAD speech time with few/no transcribed words | usually fillers or mumbling — surfaced as a data-quality note |

All thresholds in config, defaults as above. Metrics output is a flat dict → JSON.

### E. LLM examiner (skippable with `--no-llm`)
- Input: full transcript, metrics dict, `tema`, `ejercicio`, low-confidence span hints.
- Prompt contract (versioned string in `prompts/{prompt_version}.md`, currently `examiner_v2.md` — version recorded in output, since prompt changes break comparability of scores; superseded versions are kept):
  - Role: acreditado DELE B2 oral examiner, peninsular Spanish.
  - Caveats given to model: transcript may have silently corrected learner errors; filler counts are underestimates; do not comment on pronunciation (not observable from text).
  - Tasks: (1) score 1–3 per rubric criterion — coherencia, fluidez, corrección, alcance — with one-line justification; (2) errors grouped **by pattern**, `tipo | patrón | debería ser | por qué | instancias` (only errors visible in transcript, max 10 **patterns**, calques first then most instructive); (3) subjunctive check on any matched trigger connectors (`de ahí que`, `a menos que`, …) — correct/incorrect per instance; (4) 2–3 upgrade suggestions: phrases the speaker used a rodeo for, with the B2 chunk that replaces them; (5) one focus for next session.
  - Output: **structured outputs** — the request carries the `ExaminerResult` schema, so the API constrains generation and the response *shape* (field names, types, the `tipo` enum, required keys) cannot come back wrong. No JSON is parsed out of prose.
  - The API rejects count and range constraints, so the SDK folds them into each field's `description`: max 10 patterns, scores 1–3, and 2–3 mejoras are hints the model reads but only pydantic enforces, client-side. A violation there is the one case the single retry exists for; after it, the feedback section is marked failed.
  - `output_schema_v2.json` is documentation of the contract; `examiner.ExaminerResult` is the executable source of truth.

#### Error grouping and `tipo` (examiner_v2)

A repeated fault is **one row carrying every occurrence in `instancias`**, not one row per occurrence. The cap therefore budgets distinct faults to work on: six `por`/`para` slips take one slot instead of crowding out five other error types. `len(instancias)` becomes a severity signal the flat list threw away.

`tipo` ∈ `calco` | `gramatica` | `lexico` | `registro`:

- **`calco`** — structure or idiom translated literally from English; usually grammatical but unidiomatic (*hacer sentido*, *aplicar para un trabajo*, *estoy bueno*), including false friends used with the English sense (*realizar*, *soportar*, *eventualmente*). **Priority category**: an error matching `calco` and another type is tagged `calco`, and calques sort first.
- **`gramatica`** — agreement, tense, mood, prepositional régimen.
- **`lexico`** — wrong word with no identifiable English origin.
- **`registro`** — wrong formality for the context.

Loanwords (*email*, *random*, *software*) are deliberately **not** a category and are not reported: acceptance varies by region and register, so they are noise rather than learner error. A loanword only counts when it is part of a structural calque.

### F. Outputs

Paths below are shown relative to the resolved base (`{vault}/Español` for a vault, `{out}` otherwise).

1. **Session note** → `{base}/Sesiones/YYYY-MM-DD {ejercicio}.md`
   - Frontmatter per vault convention: `type: sesion`, `ejercicio`, `fecha`, `duracion` (minutes, from audio), `tema`, `fuente: analiza`.
   - Body: metrics summary block, examiner scores, a "Calcos" section (calques listed with every instance quoted, so they are not buried among grammar rows), error table for the remaining types (pre-filled, vault table format), upgrade suggestions rendered as `frase :: contexto` bullets under "Chunks capturados" — so the weekly-review promotion flow applies unchanged.
   - Collision: if the file exists, append ` (2)`.
2. **Stats row** → `{base}/analiza-stats.csv`
   - `date, ejercicio, tema, duration_s, wpm_gross, wpm_articulation, pauses_n, pause_max_s, fillers_per_min, connectors_unique, formal_ratio, mtld, errors_n, calcos_n, score_total, whisper_model, prompt_version`
   - `errors_n` and `calcos_n` count **patterns**, not occurrences, from `examiner_v2` on; under `v1` `errors_n` counted rows. Filter on `prompt_version` before trending across that boundary.
   - `whisper_model` and `prompt_version` are the provenance pair. Metrics derived from word probabilities (`fillers_n`, `low_conf_spans`) move with the whisper model, and LLM columns move with the prompt; neither is comparable across a change in its own column, so both are recorded per row.
   - Append-only; this is the 90-day trend line. Never contains LLM prose, only numbers.
3. **Raw artifacts** → `{base}/analiza-raw/YYYY-MM-DD-{ejercicio}/`: source audio copy (optional, config), whisper JSON, metrics JSON, LLM response JSON.

## 3. Module layout

```
analiza/
  cli.py            # arg parsing, orchestration, exit codes
  audio.py          # ffmpeg preprocess, duration
  transcribe.py     # faster-whisper wrapper, raw JSON persistence
  vad.py            # silero segments, silence stats
  metrics.py        # pure functions, no I/O — unit-test target
  connectors.py     # matching engine over conectores_b2.py data
  examiner.py       # prompt build, LLM call, schema validation, retry
  note.py           # obsidian note + csv rendering
  config.py
  prompts/examiner_v1.md, examiner_v2.md          # superseded versions kept
  schemas/output_schema_v1.json, output_schema_v2.json
```

`metrics.py` and `connectors.py` take plain data structures and return plain data structures — fully testable without audio. Test fixtures: 3–4 hand-annotated short recordings (one clean, one filler-heavy, one with long pauses, one mumbled) with expected metric ranges.

## 4. Dependencies

`faster-whisper` (brings silero VAD + ctranslate2, CUDA-accelerated on the 5070 Ti), `ffmpeg` (system), `spacy` + `es_core_news_sm`, `typer` (CLI), `pydantic` (config + LLM schema), provider SDK for examiner model. No Pipecat, no streaming — deliberately boring batch code.

## 5. Known limitations (documented in --help and README)

- Whisper silently corrects some learner errors → error table is a lower bound; periodically spot-check transcript vs audio.
- Filler counts are floors (suppression) → trend direction is meaningful, absolute value is not.
- Pronunciation is out of scope for v0.x → see v2.
- Scores from different `prompt_version`s are not comparable → CSV records the version; trend analysis should filter on it.

## 6. Later (explicitly not v0.1)

- **v1.1** `analiza stats` subcommand: plot WPM/formal-ratio/MTLD trends from the CSV; flag plateaus.
- **v1.2** batch mode: `analiza backfill dir/` for reprocessing old recordings from persisted raw JSON.
- **v2** pronunciation pass: send audio natively to a multimodal model for pace/intonation/specific-sound feedback; separate note section, separate prompt version.
- **v2** Habla integration: "monólogo mode" — Habla serves the topic + timed prep, records, then shells out to `analiza`. Shared assets: examiner prompt, rubric schema, connector list.
```
