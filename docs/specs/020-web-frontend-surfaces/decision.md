# Decision Record: Web Frontend — Wire the Dead Surfaces to Live Data

| Field | Value |
|---|---|
| id | 020 |
| status | implemented |
| created | 2026-07-25 |
| spec | [spec.md](./spec.md) |

---

## Context

#019 shipped three authed read endpoints and no consumer. #023 shipped a
`?mode=&topic=` contract and no picker. So the deployed app still told a learner
who had been promoted to B1 that they were `A2 · inicial`, with "aún no hay"
sessions and six invented topic cards — the complaint that triggered the
2026-07-12 audit, still true three specs later.

Two things shaped the work beyond the spec.

**The validation gate paid for itself immediately.** The spec made seeding a
realistic database and curling the endpoints a blocking first step. It confirmed
all three endpoints support the specced screens (no #019 amendment needed), and
surfaced one thing worth knowing before any component existed: `top_vocab` and
`vocab_strengths` are ordered by `last_seen_at`, not `production_count`
(`read.py:60-66`) — so a word produced twice yesterday outranks one produced
nine times last week. `vocab_strengths` is a misnomer; it is recency.

**Browser verification found three real defects that no unit test would have.**
Playwright browsers turned out to be available locally, so rather than stopping
at "the build is green", every screen was rendered against the seeded database
and against an empty one. That produced the three fixes in commit `01ea6aa` —
including one where the screen was inventing progress a learner had not made.
This was the first spec in the series whose verification did not have to be
deferred to a keyed host.

## Decision

Ship the full seven workstreams: an in-repo history router and a typed API
client with per-surface hooks; Home's tiles, topic cards, nav, avatar and
"ver todo" reading live data; three new screens (Progreso / Historial /
Ajustes) in María's register rather than as a metrics dashboard; Session's live
band badge; a mode/topic picker on #023's contract; and Vitest over the pure
logic that moved client-side.

No backend change, no migration, no new runtime dependency — `web/`'s runtime
deps remain `react` + `react-dom`. The learner name and avatar initial stay
hardcoded, deliberately: #021 owns the identity model and its schema question.

---

## Alternatives Considered

### Routing

**Option A: `react-router-dom`**
- Pros: standard, familiar, handles params and nesting.
- Cons: a runtime dependency and bundle cost for five flat routes with no params.

**Option B: ~40 lines over `history.pushState` + `popstate`**
- Pros: no dependency; the edge already serves deep links (`try_files` in the
  prod Caddyfile, Vite dev server likewise).
- Cons: hand-rolled; would need replacing if route params ever appear.

**Chosen: B** (spec OQ1). The codebase has exactly two runtime dependencies and
no CSS framework or state library; adding a router for five flat routes would
have been the first exception, and nothing here needs one.

### Recovering from a rejected token

**Option A: each screen checks whether its read failed with 401.**
- Pros: local, explicit, no shared state.
- Cons: **does not work.** Verified in the browser: a 401 clears the token
  inside `apiGet`, which re-runs every hook with no token and wipes the error
  before any screen observes it. The user was left on a blank screen with no
  data, no error, and no prompt.

**Option B: one rule about the token, in `App`.**
- Pros: covers the 401 path, a deep link with no token, and a manual clear from
  Ajustes, with one statement; cannot be defeated by the error being cleared.
- Cons: slightly less local; screens no longer own their auth recovery.

**Chosen: B** (`useAuthGuard`). Option A was written first and shipped in the
WS2–WS5 commit; browser verification proved it did not work, and it was replaced.

### Making token writes visible to the data hooks

**Option A: leave the hooks fetching once on mount.**
- Pros: simplest.
- Cons: pasting a token populated nothing until a reload, and the guaranteed
  401 from a tokenless first load raced in and cleared the token the operator
  had just typed. Both observed in the browser.

**Option B: `sessionStorage` writes announce a custom event; hooks subscribe
via `useSyncExternalStore` and skip fetching entirely with no token.**
- Pros: fixes both; removes a guaranteed-401 request on every tokenless load.
- Cons: a small amount of machinery in what was a three-function module.

**Chosen: B.** `sessionStorage` fires no event for same-tab writes, so this
signal simply did not exist and had to be added.

### Vocabulary ordering

**Option A: render `top_vocab` in API order.**
- Pros: no client logic; matches the endpoint exactly.
- Cons: that order is recency, so "palabras que ya produces" would lead with a
  word used twice.

**Option B: sort by `production_count` client-side.**
- Pros: matches what the panel claims; `production_count` is already in the
  payload.
- Cons: view and API disagree on ordering, which could confuse a future reader.

**Chosen: B**, with the reason written into `vocabByProduction`'s docstring.
Changing the API's `ORDER BY` was rejected as out of scope — #020 adds no
backend surface, and `/dev/learner` shares that query.

### Web test infrastructure

**Option A: build gate only** (`tsc --noEmit && vite build`), as before.
**Option B: Vitest over the pure helpers, no jsdom, no component rendering.**

**Chosen: B** (spec OQ4). The streak calculation alone — day boundaries, local
timezone, same-day pairs, the grace day before a streak breaks — is the kind of
thing that is silently wrong for months.

---

## Tradeoffs

- **Client-side derivation over new endpoints.** Streak, duration, relative
  time, topic dedup and vocabulary ordering are all computed in the browser.
  This honours #019's OQ4 resolution and keeps presentation choices out of the
  API contract, at the cost of logic that only exists on one client. Mitigated
  by making exactly that logic the thing Vitest covers.
- **Per-surface failure over a global error boundary.** Each hook owns its
  `{data, error, loading}`, so one dead endpoint degrades one region. More
  wiring than a single boundary; the difference between a page that looks broken
  and a page that looks honest.
- **A hand-rolled router.** Zero dependencies today; a rewrite if route params
  are ever needed.
- **No component tests.** Node-environment Vitest covers pure logic; everything
  React-shaped is covered by the build gate and the browser checklist below.
  A regression in a screen's rendering would not be caught by CI.
- **Fixed desktop layout.** New screens match the existing 80px-padding desktop
  chrome. A responsive pass remains separate work.
- **`sessions_completed === 0` as the "no signal yet" proxy.** The profile
  payload carries no turn count, so this is the closest available test for
  "these numbers mean nothing yet". A session that logged zero turns would slip
  past it — harmless, and the alternative was an API change.

---

### Spec Divergence

The implementation matches the spec. All 26 acceptance criteria were built as
written, with all five Open Questions implemented at their approved
resolutions. Three additions were made that the spec did not name:

| Spec Said | What Was Built | Reason |
|---|---|---|
| Screens read the API; recovery on 401 is "return to the Home token prompt" | Plus `useSessionToken` / `subscribeToken` — a token-change signal the hooks subscribe to | Without it the hooks fetched once on mount: pasting a token populated nothing until reload, and a tokenless load's 401 cleared the token just typed. Found in browser verification. |
| — | `useAuthGuard` in `App`, replacing per-screen 401 checks | The per-screen approach cannot work; see Alternatives. |
| Progreso shows `l1_reliance` / `speech_fluency` as bounded 0–1 readouts | Shown only when `sessions_completed > 0` | The API returns a neutral `0.5` for both with no turns. Rendering that as a half-full meter invents progress — the precise failure mode this spec exists to remove. |

The seeder (`scripts/seed_dev_learner.py`) was committed rather than treated as
throwaway; the spec permitted either.

---

## Spec Gaps Exposed

1. **`vocab_strengths` is misnamed** (#019). It is the five most *recently* seen
   lemmas, not the strongest. `/api/learner` and `/dev/learner` both expose it
   under that name. Candidate for a #019 amendment (rename, or add an explicit
   ordering parameter) — worked around client-side here.
2. **`l1_reliance` / `speech_fluency` carry no "no data" signal.** They return
   `0.5` whether the learner is genuinely mid-scale or has never spoken. Any
   future consumer must infer emptiness from elsewhere, as this one does from
   `sessions_completed`. A nullable signal, or a `turns_observed` count in the
   payload, would remove the guess.
3. **`/api/learner/sessions` exposes no total count.** Pagination therefore ends
   on a short page. Fine for "cargar más"; a page-number UI would need a count.
4. **The error-category vocabulary is unbounded.** `errors[].type` in the
   `log_turn` schema (`hable_ya/tools/schema.py:65`) is a bare
   `{"type": "string"}` with no enum, and the prompt only offers an example
   (`render.py:234`). `error_counts.category` therefore holds whatever Claude
   writes — English snake_case, Spanish prose, or novel phrasings, all observed
   in one seeded list. `errorLabel()` maps the 12 curated slugs in
   `eval/agent/personas/schema.py:31-46` and prettifies the rest. Constraining
   the schema is a real follow-up candidate: it would make the learner model's
   own aggregates sharper, not just the UI's labels.
5. **#024's `response_latency_ms` still has no read path.** Persisted to
   `turns.raw_extra` but exposed by no endpoint, so it stays out of #020 as
   planned. Surfacing it needs a null-aware aggregate API-side first (absent key
   = "not measured", for first turns and barge-ins).
6. **Home's token gate ignores server config.** It gates the CTA on a stored
   token regardless of `session_auth_disabled`, so a developer running with auth
   off must still paste a dummy value. Not changed here (it would be an auth
   behaviour change); Ajustes' clear-token control makes the loop workable.

---

## Test Evidence

**Frontend unit tests** (`cd web && npm test`):

```
 RUN  v2.1.9 /home/adrian/Desarrollador/habla/web

 ✓ src/lib/api.test.ts (7 tests) 4ms
 ✓ src/lib/format.test.ts (30 tests) 5ms

 Test Files  2 passed (2)
      Tests  37 passed (37)
```

**Build gate** (`cd web && npm run build` = `tsc --noEmit && vite build`):

```
dist/index.html                   0.76 kB │ gzip:  0.42 kB
dist/assets/index-LLVNysuQ.css    0.99 kB │ gzip:  0.58 kB
dist/assets/index-iWnQ74wD.js   182.83 kB │ gzip: 57.65 kB
✓ built in 353ms
```

**Python suite** — unchanged, as no backend change was in scope:

```
469 passed, 9 warnings in 16.00s
```

**Lint / types:**

```
$ uv run ruff check hable_ya/ api/ eval/agent/ tests/ scripts/
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 63 source files
```

**API contract, against the seeded database** (validation step 1):

```
$ curl -s -H "Authorization: Bearer $TOKEN" .../api/learner
{"band": "B1", "sessions_completed": 12, "l1_reliance": 0.1,
 "speech_fluency": 0.735, "is_calibrated": true,
 "stable_sessions_at_band": 4, "top_errors": [
   {"category": "gender_agreement", "count": 14, ...},
   {"category": "concordancia de número", "count": 2, ...}], ...}

no token          -> 401
bad token         -> 401
limit=101         -> 422
offset=10 of 12   -> 2 rows   (short page ends pagination)
```

**Browser verification** (Playwright, Chromium, against the running API):

All four screens rendered with **zero console errors and zero page errors**.

| Check | Result |
|---|---|
| Home tiles vs seeded rows | racha `3 días` (today/yesterday/2-days-ago, gap at day 3), `B1 · 4 sesiones aquí`, última sesión `hoy · contar un sueño raro` — all match |
| Topic cards | real themes, durations, bands and mode badges; the `ended_at IS NULL` row renders `en curso` |
| Progreso | `Estás en B1.`, all five error slugs translated, vocabulary ordered by production count (`viajar ×9` first), timeline `Subiste de A2 a B1 · hace 5 días` / `Empezaste en A2 · hace 2 semanas` |
| Historial | 12 sessions newest first with mode badges; `25 jul · contar un sueño raro · DEBATE · B1 · 2 turnos · en curso` |
| Ajustes | health `Todo listo`, agent card, token replace + clear |
| Empty DB (truncated) | every tile `—`, "aún no hay", "Aún no hay temas — el primero saldrá de tu próxima conversación", Progreso `Todavía te estoy conociendo.` with no meters — no crash, no infinite spinner, nothing invented |
| Bad token | `{"landedOn": "http://localhost:5173/", "tokenCleared": true, "promptShown": true}` |
| Deep links | `/progreso`, `/historial`, `/ajustes` all serve 200 and render on reload |
| WS query params | default → `ws://localhost:5173/ws/session` (byte-identical to pre-#020); debate + topic → `ws://localhost:5173/ws/session?mode=debate&topic=la+vida+en+la+ciudad` |
| Back during a session | exits cleanly to Home (`backExited: true`) |

**Not verified — deferred:** a live per-mode session confirming Claude adopts
each posture end to end, and the deployed-host Caddy hop over real TLS. The
first needs a full STT/LLM/TTS turn against all three paid APIs; the second
needs a public domain. Same class of deferral as #016–#024. Every read path,
which is the whole of #020's data surface, was exercised locally.
