# Spec: Targeted Conversations (Modes & Theme)

| Field | Value |
|---|---|
| id | 023 |
| status | approved |
| created | 2026-07-15 |
| approved | 2026-07-15 |

---

## Why

Every session `habla` runs today is shaped identically: after the learner is
calibrated, `build_session_prompt` (`hable_ya/pipeline/prompts/builder.py:64`)
picks a conversational scenario by calling `get_session_theme`
(`hable_ya/learner/themes.py:685`), which does a **`random.choice`** over the
current band's theme pool, filtered only by a 3-domain cooldown. The learner
has no way to say *what kind of conversation* they want.

That is a missed opportunity, because the scenario content the learner would
want to steer toward **already exists**. The per-band pools in `themes.py` are
already role-plays and debates — A1/A2 entries like `"Tú eres el camarero…"` /
`"Tú eres el médico…"`, B2's `"impacto del teletrabajo"` whose prompt literally
opens *"Debate con el estudiante…"*, C1's `"dilema ético reciente"`. They are
simply selected at random and never surfaced as a choice.

This spec adds a per-session **conversation configuration**: the learner can
pick a **mode** — `open` (today's behaviour), `debate`, `role-play`, or
`interview` — and optionally supply a freeform **topic/scenario**, chosen once
at session start. It is the conversational-control feature that makes #020's
frontend worth interacting with, and it is deliberately scoped so the backend
ships and is testable *ahead of* the #020 picker UI.

### The safety argument (why this is a small, contained change)

The runtime system prompt is assembled from **independent blocks**
(`render_system_prompt`, `hable_ya/pipeline/prompts/render.py:259-355`). Only
the `## Topic:` block (`render.py:295-303`) is filled from a `Theme`. The
load-bearing pedagogical machinery lives in *separate* blocks driven by the
learner's **band**, not the theme:

- `## Response format (strict)` + `REGISTER_GUIDANCE[band]` — the tutor's
  register / vocabulary / grammar,
- `## Assessing the learner's level` — the CEFR rubric,
- `## Handling learner errors: recast, never correct` + the band recast example,
- `## After your reply, call log_turn` — the tool contract.

A `Theme` is `{domain, prompt, target_structures}` (`eval/fixtures/schema.py`).
Therefore **a "mode" is nothing more than an alternative way to construct the
`Theme` that fills the Topic block.** It cannot disable corrections, change the
register, or suppress `log_turn`, because it never touches those blocks. The
freeform topic string is likewise confined to the Topic block. The learner-model
loop (`log_turn` → Postgres/AGE writes, placement/leveling at session end) keeps
running underneath a debate exactly as it does under an open chat.

### Consumer Impact

- **The learner** gains real control over practice: rehearse a job interview,
  argue a position, or role-play a transaction on demand — at their own level,
  in simple or advanced Spanish depending on their band, with the same gentle
  recasting and silent assessment as today.
- **The `web/` SPA (#020)** gets a concrete front door: a mode/topic picker on
  Home (`[ Open ▾ ] [ Topic: __ ] → [ Start ]`) that appends the config to the
  `/ws/session` handshake. #020 does the UI wiring; #023 ships the backend
  contract and is fully exercisable without it.
- **The operator** gets a session-shaping lever that does not require touching
  the pedagogical prompt or the learner model.

### Roadmap Fit

- **Feeds / precedes #020.** The picker is a #020 surface, but the backend
  (config channel + mode factories + `sessions.mode`) is independent and
  `curl`/WS-client testable now. Land #023 first so #020 has something to wire.
- **Relates to #019** (learner-progress read API): the session-history payload
  in `hable_ya/learner/read.py` gains a `mode` field so #020 can show *"4
  debates, 2 role-plays"*. Additive; no change to #019's auth or shape contract.
- **Depends on the calibration gate** (`is_calibrated_async`,
  `hable_ya/learner/profile.py`) already used by `build_session_prompt` to
  choose between the cold-start diagnostic and a themed session.
- **Independent of #021 / #022.** No user/identity model change (stays
  single-tenant); no AGE graph reads.

---

## What

### Acceptance Criteria

- [ ] A per-session **conversation configuration** — `mode` (one of `open`,
  `debate`, `role_play`, `interview`) and an optional freeform `topic` string —
  can be supplied at session start and is honoured for that session only.
- [ ] Config is transported as **query params on `/ws/session`**
  (`?mode=&topic=`), parsed alongside the existing token extraction
  (`api/routes/session.py:58`, `_extract_token`). Absent params → `mode=open`,
  no topic (today's exact behaviour).
- [ ] Each mode is realised as a **`Theme` factory** that fills only the
  `## Topic:` block. `debate` stages the agent taking a contrary stance and
  pressing the learner to defend/rebut; `role_play` casts the agent as a
  character in a scenario with the learner pursuing a goal; `interview` casts
  the agent as an interviewer running a structured question sequence; `open`
  reproduces the current cooldown-aware random theme pick (or, if a topic is
  given, an open chat steered to that topic).
- [ ] **No level-gating of the mode.** Any mode is available at any band (A1–C1).
  The learner's band continues to scale *only the tutor's own vocabulary and
  grammar*, via the existing untouched `REGISTER_GUIDANCE`/rubric/recast blocks.
  Each mode factory MAY attach light per-band `target_structures` hints
  (elicitation targets), but never gates availability by band.
- [ ] Config is **ignored until the learner is calibrated.** While
  `is_calibrated_async` is false, `build_session_prompt` still emits the
  cold-start diagnostic ladder unchanged, regardless of any `mode`/`topic`
  supplied. The existing cold-start byte-identity tests in
  `tests/test_prompts.py` stay green.
- [ ] An **unknown/invalid `mode`** value falls back to `open` (fail-safe, never
  a 4xx/5xx on the WS handshake). An empty `topic` is treated as "no topic".
- [ ] The chosen mode is **persisted**: a nullable `sessions.mode` column
  (values `open|debate|role_play|interview`, `NULL` for legacy rows), written by
  `TurnIngestService.start_session` (`hable_ya/learner/ingest.py:79`). The
  session `theme_domain` continues to be written (a synthetic domain label for
  moded sessions, e.g. the topic or a `"debate: <topic>"` slug).
- [ ] The #019 session-history read (`hable_ya/learner/read.py::session_history`)
  returns `mode` per session, so #020 can render it. No change to #019's auth.
- [ ] `log_turn` / `end_session` / placement / leveling are **unchanged**. The
  per-turn learner-model writes run identically in every mode.

### Non-Goals

- **No mid-session switching.** The mode is fixed for a session (the system
  prompt is set once at `LLMContext` construction). Live switching would require
  mid-pipeline context surgery and a control channel — explicitly deferred.
- **No structured per-mode sub-parameters in v1** (no separate `stance`,
  `formality`, `agent_role`, `learner_goal` fields). A single freeform `topic`
  string carries the specifics; the model interprets it within the mode
  template. Structured params are a later enhancement (see Open Questions).
- **No new UI.** The mode/topic picker is #020. This spec ships the backend
  channel, the mode factories, the migration, and their tests only.
- **No multi-user / identity change.** Single-tenant `learner_profile CHECK
  (id = 1)` is untouched. Whoever the deployment serves picks the mode. (#021.)
- **No change to the pedagogical core.** Register, rubric, recast contract, and
  the `log_turn` tool schema are out of scope and must not change.
- **No AGE graph reads** (#022) and **no new dependency**.

### Open Questions

All resolved 2026-07-15 with the recommended default accepted in each case.

1. **Query-param shape.** **Resolved: flat `?mode=<enum>&topic=<text>`**
   (URL-encoded topic), parsed like the existing `?token=`. A single JSON blob is
   rejected as heavier for no v1 benefit. The topic is not a secret; only the
   session **token** is kept out of URLs, and it still rides the
   subprotocol/`?token=` path unchanged.
2. **Structured sub-params vs. one freeform string.** **Resolved: one freeform
   `topic` per mode.** A role-play scenario like *"Tú eres el camarero y el
   estudiante quiere reservar una mesa"* is expressible as free text; the model
   interprets it inside the mode template. Structured sub-params (`stance`,
   `agent_role`, `learner_goal`, `formality`, `interviewer_role`) are a later
   enhancement, additive over this channel, revisited only if #020's single-field
   UX proves awkward.
3. **Per-band `target_structures` for the parametric modes.** **Resolved:
   minimal — author per-band hint sets for `debate` and `interview` only**;
   `role_play` and `open`-with-topic ship with empty `target_structures` (the
   band register block already scales the tutor). Hints are optional in the
   renderer, so this can be enriched later without a contract change.
4. **`theme_domain` for moded sessions.** **Resolved: a `"<mode>: <topic>"`
   slug** when a topic is given (e.g. `"debate: teletrabajo"`), falling back to
   the bare mode name when it is not (e.g. `"debate"`). Readable in #020 history,
   keeps the cooldown meaningful, and self-documents alongside `sessions.mode`.
5. **Should `open` + explicit topic override the random pick?** **Resolved: yes.**
   "Just talk about X" is a valid request and topic is orthogonal to mode. When
   `open` has no topic, behaviour is byte-identical to today's random cooldown
   pick.

---

## How

### Approach

Four small, independent pieces. Nothing in the pedagogical prompt path changes.

**1. A conversation-config value object + query-param parsing.**
Add a frozen dataclass (e.g. `hable_ya/pipeline/conversation.py::ConversationConfig`
with `mode: ConversationMode` and `topic: str | None`) and a parser mirroring
`_extract_token` — `_extract_conversation_config(websocket)` in
`api/routes/session.py` reading `websocket.query_params.get("mode")` /
`get("topic")`, normalising an unknown/blank mode to `open`. Parsed right after
the auth gate in `session_ws` (`session.py:143`), before the prompt build.

**2. Mode → `Theme` factories (the only genuinely new content).**
A new pure module `hable_ya/learner/modes.py`:
`build_mode_theme(config, *, level, recent_domains, cooldown) -> Theme`.
- `open` → delegates to the existing `get_session_theme(...)` when no topic; with
  a topic, returns an open-chat `Theme` steered to that topic.
- `debate` → a `Theme` whose Spanish `prompt` instructs the agent to take a
  contrary stance on `topic` (or a band-appropriate default subject) and press
  the learner to justify/rebut, with per-band argument-connector
  `target_structures` (see OQ3).
- `role_play` → a `Theme` staging a scenario from `topic` (agent as a character,
  learner with a goal); transactional structures.
- `interview` → a `Theme` casting the agent as an interviewer running a
  structured question sequence about `topic`.
The band is threaded through only so a factory can pick a band-appropriate
default subject and hint set — **it never gates the mode.** Factories return the
same `Theme` shape the renderer already consumes, so `render.py` is untouched.

**3. Thread the config through `build_session_prompt`.**
Add a `conversation_config: ConversationConfig | None = None` keyword param
(`builder.py:64`). In the **calibrated** branch only (`builder.py:91-99`),
replace the unconditional `get_session_theme(...)` with: if a non-`open` mode or
a topic is set, `build_mode_theme(...)`; else the current random pick. The
**uncalibrated** branch is unchanged — config is dropped, cold-start diagnostic
preserved (satisfies the "ignored until calibrated" criterion and keeps the
byte-identity tests green). `session_ws` passes the parsed config through
(`session.py:173-175`).

**4. Persist `sessions.mode`.**
New Alembic migration revising the current head `99507a1b3027`
(`ADD COLUMN mode TEXT` on `sessions`, nullable, `CHECK (mode IS NULL OR mode IN
('open','debate','role_play','interview'))`, using the same
`SET LOCAL search_path TO public, ag_catalog;` scoping convention as
`99507a1b3027`). `SessionPrompt` (`builder.py:37`) gains a `mode` field;
`start_session` (`ingest.py:79`) takes `mode` and includes it in the `sessions`
INSERT; `session_ws` passes `session_prompt.mode` at `session.py:212-218`.
Finally, extend `hable_ya/learner/read.py::session_history` to select `mode`, so
#019's endpoint (and the re-pointed `/dev/learner`) surface it for #020.

Data-flow note: the model still speaks first (no scripted greeting); the mode
lands entirely in the system prompt at `LLMContext` construction
(`session.py:178-181`). No pipeline/observer/serializer change.

### Confidence

**Level:** High (mechanics) / Medium (mode-prompt copy quality)

**Rationale:** The injection points are narrow and already isolated — one new
keyword param on `build_session_prompt`, a query-param read that mirrors the
existing `_extract_token`, one new pure module of `Theme` factories, and one
nullable column with a standard migration. No schema reshaping, no new
dependency, no change to the tool schema, the renderer, the pipeline, or the
learner-model writes. The "safe by construction" argument (mode fills only the
Topic block) is structural, not incidental.

The residual uncertainty is **content, not architecture**: whether the Spanish
mode-prompt templates reliably make Claude adopt a debate/interview posture at
each band while still emitting `log_turn`. That is resolved by a live smoke of
one session per mode (see Testing), deferred to a keyed spike as in prior specs
(#016/#018/#019 all deferred the live-keyed leg).

### Key Decisions

- **A mode is a `Theme` factory, not a prompt rewrite.** Confines all new prose
  to the Topic block, keeping the recast / register / `log_turn` contract
  untouched — the whole reason a debate can't silently degrade the learner model.
- **No level-gating of the kind; band scales only the tutor's language.** Debate
  at A2 is allowed (simple debate in simple Spanish) — the existing band blocks
  already scale the tutor's register; the mode is orthogonal.
- **Per-session at start, no mid-session switch.** Matches the once-set system
  prompt and keeps the pipeline untouched; a much larger live-switch design is
  explicitly out of scope.
- **Ignored until calibrated.** Preserves the placement diagnostic; config only
  bites once `is_calibrated_async` is true.
- **Fail-safe config.** Unknown mode / blank topic degrade to `open`; a bad query
  param never breaks the handshake.
- **Query params, not the token channel.** The topic isn't secret; keep the
  token's subprotocol/`?token=` path unchanged and read `mode`/`topic`
  separately.

### Testing Approach

Per the existing suite (pytest + `pytest-asyncio`; DB-marked tests run when the
`db` service is up; CI-scoped ruff + mypy over `api/` and `hable_ya/`):

- **Mode factories (pure, no DB):** `build_mode_theme` returns a `Theme` whose
  prompt reflects the mode for each `(mode, band, topic)`; the freeform topic
  appears in the Topic prose; per-band `target_structures` differ across bands
  for `debate`/`interview`; unknown mode → `open`; empty topic handled.
- **Query-param parsing:** `_extract_conversation_config` maps `?mode=debate` /
  `?topic=...` correctly; missing → `open`/none; unknown mode → `open`; parsing
  is independent of and does not disturb token extraction.
- **`build_session_prompt` wiring:** with a calibrated profile, a `debate` config
  routes through `build_mode_theme` (Topic block reflects debate); with an
  **uncalibrated** profile, the same config is ignored and the cold-start
  prompt is byte-identical to today (existing `tests/test_prompts.py` stay
  green).
- **Persistence (DB):** `start_session` writes `sessions.mode`; a fresh moded
  session round-trips through `read.py::session_history` with the right `mode`;
  legacy rows (`NULL`) deserialize fine.
- **Migration:** upgrade/downgrade of the new revision on a seeded DB; the
  `CHECK` rejects an out-of-set value.
- **Learner-model invariance:** a moded session still ingests `turns` /
  `error_counts` / `vocabulary_items` and runs placement/leveling identically —
  assert no behavioural change in `log_turn` handling across modes.
- **Live smoke (deferred, keyed):** one real `/ws/session` per mode (debate,
  role-play, interview) confirming Claude adopts the posture, replies in
  band-appropriate Spanish, and still emits exactly one `log_turn` per turn.
