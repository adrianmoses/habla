# Spec: Web Frontend — Wire the Dead Surfaces to Live Data

| Field | Value |
|---|---|
| id | 020 |
| status | approved |
| created | 2026-07-25 |
| approved | 2026-07-25 |

---

## Why

The learner model runs end to end and is now *readable* — and none of it is
visible. Every turn writes a `turns` row, `error_counts`, lemmatized
`vocabulary_items`, and AGE graph upserts; `end_session` runs real
placement/leveling that writes `band_history` and updates `learner_profile`.
#019 exposed all of it over three authed endpoints (`/api/learner`,
`/api/learner/sessions`, `/api/learner/band-history`), reverse-proxied
same-origin by the prod Caddyfile and by the Vite dev proxy. #023 then made a
session steerable into debate / role-play / interview via `?mode=&topic=` on
`/ws/session`.

The SPA consumes none of it. It ships exactly two screens (`Home`, `Session`)
and every other surface is a decorative stub:

- `Home.tsx:112-116` — `Progreso` fires a "próximamente" toast; `Historial` and
  `Ajustes` are bare `<a>` elements with no `href` and no `onClick`, styled
  `cursor: 'pointer'` (`navLinkStyle`, line 17-22). They look like navigation
  and do nothing.
- `Home.tsx:117-134` — the profile avatar is a `cursor: pointer` div that also
  just toasts.
- `Home.tsx:378-446` — the three stats tiles are a hardcoded array: racha `'—'`,
  nivel `'A2'` / `'inicial'`, última sesión `'—'` / `'aún no hay'`. The comment
  still cites the pre-port specs (`#026` / `#029`).
- `Home.tsx:511` — "ver todo →" is an `<a>` with no target.
- `Home.tsx:517-560` — six recent-topic cards are a hardcoded literal
  (`['Pedir en un restaurante', '8 min', 'A2']`, …), `cursor: pointer`, no
  handler, under a heading that claims they are "temas recientes".
- `Session.tsx:166-183` — the `NIVEL A2` badge is static; the comment points at
  specs `#029–#033`.

So a learner who has completed ten sessions and been promoted to B1 sees a page
that says `A2 · inicial`, "aún no hay" sessions, and six topics they never
discussed. The product reads as though it neither logs nor adapts — which is
precisely the complaint that triggered the 2026-07-12 post-deploy audit. The
loop is real; the window onto it is painted on.

This spec builds that window: three new screens on #019's API, live values in
the two existing screens, and — because a card that shows a real topic and still
does nothing is the same lie in a nicer font — a session-start path that
actually uses the topic, via #023's mode/topic query params.

### Consumer Impact

- **The learner** (single-tenant, the one person a deployment serves) gets the
  payoff for a learner model that has been running invisibly: their current CEFR
  band and whether they are calibrated, how many sessions they have completed,
  what they keep getting wrong (`top_errors`) and what vocabulary they are
  actually producing (`top_vocab`), a session history with dates, topics, modes
  and turn counts, and a band-change timeline showing when and why they moved.
  They also gain the ability to *choose* what a session is about — a debate, a
  role-play, an interview, or a specific topic — instead of accepting a random
  cooldown-filtered theme.
- **The operator** stops needing `dev_endpoints_enabled` (blanket-open, "do not
  use in production") to answer "is this thing learning anything?". The Ajustes
  screen also gives them a way to replace or clear the session token without
  hand-editing `sessionStorage` in devtools — today the only exit from a stale
  token is a `1008` close on a session attempt (`Session.tsx:38-42`).
- **The `/api/learner*` endpoints** get their first real client. #019 shipped
  the contract with no consumer; this spec is the consumer, and it is the pass
  that will show whether the payload shapes are actually sufficient.

### Roadmap Fit

- **Depends on #019** (learner-progress read API) — shipped 2026-07-12. Every
  screen here reads it; no new backend read work is expected.
- **Depends on #018** (web frontend auth + deploy) — shipped. Supplies the
  token-in-`sessionStorage` model (`lib/token.ts`), the built-SPA-behind-Caddy
  serving path, the `/api/*` Caddy handle and Vite proxy, and the CI web build
  gate.
- **Consumes #023** (targeted conversations) — shipped. #023's roadmap row
  explicitly parks "the picker UI" here; the mode/topic query-param contract on
  `/ws/session` is live and `curl`-testable today with no server change.
- **Explicitly not #021** (learner identity). The greeting still says "Ana"
  (`Home.tsx:175-176`) and the avatar still shows `A`. Fixing that needs an
  owner-configurable name in the profile, which is #021's schema/API question.
  This spec leaves both alone and cross-references them, rather than smuggling
  in half a learner-identity feature.
- **Explicitly not #022** (graph read path). Nothing here reads AGE; the screens
  render the same relational aggregates that already drive adaptivity.
- **Unblocked by nothing else.** #014 (resilience/cost) and #022 are orthogonal
  and can land before or after.

---

## What

### Acceptance Criteria

**Navigation**

- [ ] `Progreso`, `Historial`, and `Ajustes` navigate to real screens. No
  surface in the app is styled `cursor: pointer` while doing nothing, and the
  "próximamente" toast is deleted along with the last surface that needed it.
- [ ] The three new screens are reachable by URL (`/progreso`, `/historial`,
  `/ajustes`), survive a page reload, and work with browser back/forward — the
  prod Caddyfile already serves `try_files {path} /index.html` for exactly this.
- [ ] The profile avatar navigates to Ajustes.

**Home — live values**

- [ ] `NIVEL ACTUAL` shows the learner's real `band`, with a sub-label that
  distinguishes calibrated from not (`is_calibrated`), instead of the hardcoded
  `A2 · inicial`.
- [ ] `ÚLTIMA SESIÓN` shows a relative time derived from the most recent
  session, and `RACHA` shows a consecutive-day streak computed client-side from
  the session list (#019 Open Question 4 resolved to client-side).
- [ ] The recent-topic cards render real sessions — `theme_domain`, real
  duration from `started_at`/`ended_at`, and `band_at_start` — newest first,
  with the session's `mode` visible when it is not `open`.
- [ ] "ver todo →" navigates to Historial.
- [ ] With a fresh database (zero sessions) every tile and the card strip render
  honest empty copy — never a spinner that never resolves, a blank region, or a
  crash.

**Progreso**

- [ ] Shows the current band, calibration state, `sessions_completed`, and
  `stable_sessions_at_band`.
- [ ] Shows a band-change timeline from `/api/learner/band-history`:
  `from_band → to_band`, `reason`, and `changed_at`, newest first.
- [ ] Shows `top_errors` (category + count) and `top_vocab` (lemma +
  `production_count`) from the profile payload.
- [ ] Shows `l1_reliance` and `speech_fluency` as bounded 0–1 readouts, labelled
  in plain Spanish rather than by their raw field names.
- [ ] Renders correctly for an uncalibrated learner with empty lists.

**Historial**

- [ ] Lists sessions newest first from `/api/learner/sessions`, each showing
  date/time, `theme_domain`, `mode`, `band_at_start`, `turn_count`, and duration.
- [ ] Paginates via `limit`/`offset` (a "cargar más" control), respecting the
  endpoint's `limit ≤ 100` bound.
- [ ] A session with `ended_at IS NULL` (crashed/abandoned — the runtime only
  sets it in `end_session`) renders as in-progress/unknown duration, not as a
  negative or `NaN` duration.

**Ajustes**

- [ ] Shows connection status from the existing `/health` poll and the
  configured agent voice (the read-only María card currently inlined on Home).
- [ ] Lets the operator replace or clear the stored session token, and states
  plainly that it lives only in this tab.
- [ ] Does **not** offer a learner-name field (that is #021).

**Session**

- [ ] The `NIVEL` badge shows the learner's real band, not `A2`.
- [ ] A session can be started with a conversation mode (open / debate /
  role-play / interview) and an optional freeform topic, carried to
  `/ws/session` as `?mode=&topic=` alongside the existing subprotocol token.
- [ ] Starting a session from a recent-topic card carries that topic.
- [ ] With no explicit choice the request is byte-identical to today's (open
  mode, no topic → server-side random theme pick).

**Cross-cutting**

- [ ] Every `/api/learner*` request carries `Authorization: Bearer <token>` from
  `sessionStorage`; a `401` clears the stored token and returns the user to the
  Home token prompt — the same recovery path `Session.tsx` already implements
  for a `1008` WS close.
- [ ] A failed or slow API call degrades to a visible, non-blocking error state
  per surface; one dead endpoint never blanks the whole page.
- [ ] `npm run build` (`tsc --noEmit && vite build`) stays green; the CI `web`
  job continues to gate it.

### Non-Goals

- **No learner name / identity.** The "Ana" greeting (`Home.tsx:175-176`) and
  the `A` avatar initial stay untouched — #021 owns them, and it carries a
  schema decision (whether to drop `learner_profile CHECK (id = 1)`) that this
  spec must not pre-empt.
- **No new backend endpoints or schema changes.** If a screen wants a field
  #019 does not return, the screen adapts or the field is dropped — a #019
  amendment is a separate, deliberate change.
- **No response-latency surfacing.** #024 persists `response_latency_ms` into
  `turns.raw_extra`, and its decision record defers UI to "#019/#020" — but #019
  shipped without exposing it, so there is no endpoint to read. Surfacing it
  needs a null-aware aggregate on the API side first. Out of scope; recorded as
  a follow-up.
- **No AGE graph reads** (#022) and **no token-cost / usage metrics** (#014).
- **No write operations.** No renaming, deleting, or editing sessions; no band
  overrides. The API is read-only by construction.
- **No auth-model change.** Same #016 shared secret, same fail-closed posture,
  same paste-once transport. No cookies, no login screen, no CORS.
- **No responsive/mobile redesign.** The existing screens are fixed desktop
  layouts (`Home.tsx:142` `gridTemplateColumns: '1.2fr 1fr'`, 80px padding); new
  screens match that, and a responsive pass is separate work.
- **No design-system extraction.** Styling stays inline-style + CSS custom
  properties from `styles/tokens.css`, matching the existing two screens. No
  CSS-in-JS library, no Tailwind.
- **No mid-session mode switching.** #023 fixed the mode at session start by
  design; the picker mirrors that.

### Open Questions

All five resolved at approval (2026-07-25) — the recommended default was
accepted in each case.

1. **Router: new dependency or ~40 lines in-repo?** `App.tsx:5-30` is a
   hand-rolled two-state machine with no URL involvement, and `web/package.json`
   has exactly two runtime deps (react, react-dom). Going to five screens with
   deep links needs *something*.
   **Resolved: a minimal in-repo router** — a `useRoute()` hook over
   `history.pushState` + `popstate`, a `navigate(path)` helper, and a `switch`
   in `App.tsx`. No new dependency, no nested routes or params needed, ~40
   lines. Caddy's SPA fallback and the Vite dev server already serve any path to
   `index.html`. `react-router-dom` (~10 kB gz) is rejected as disproportionate
   for five flat routes and inconsistent with the codebase's demonstrated
   minimal-dependency posture. Revisit if route params ever appear.

2. **Is the live session URL-addressable?** If routes become real URLs, a reload
   on `/sesion` would re-mount `Session`, which immediately calls
   `getUserMedia` and opens a paid-API WebSocket.
   **Resolved: no.** The active session stays in-app state on the Home route (as
   today), not a URL. A session is a device-permission-bearing, non-restorable
   resource; restoring it from a bookmark is wrong. While a session is live,
   push one history entry so browser Back performs a clean `disconnect()` + exit
   rather than abandoning an open socket.

3. **Does the mode/topic picker land in #020 or split out?** #023's roadmap row
   assigns "the picker UI" to #020, and it is what makes the topic cards
   genuinely functional rather than merely accurate.
   **Resolved: included**, as the last workstream (WS6) so it stays severable.
   Should it ever be cut, the topic cards must become non-interactive (no
   `cursor: pointer`) rather than shipping as decorative-but-live — the whole
   point of this spec is that a surface must not look actionable and do nothing.

4. **Web test infrastructure: add Vitest, or stay build-gate-only?** `web/` has
   no test runner today; CI's `web` job runs `npm run build` only. The genuinely
   error-prone logic here is pure and small: consecutive-day streak computation
   (day boundaries, local timezone, duplicate same-day sessions), duration and
   relative-time formatting (null `ended_at`), and the API client's 401 path.
   **Resolved: add `vitest` as a dev dependency and unit-test the pure helpers
   only** — no jsdom, no React Testing Library, no component rendering. One dev
   dep, a `test` script, one CI step. The streak calculation in particular is
   the kind of thing that is silently wrong for months.

5. **How are the recent-topic cards deduplicated?** `/api/learner/sessions`
   returns sessions, not distinct topics, and a learner may do "pedir un café"
   three times.
   **Resolved: most-recent-session-per-distinct-`theme_domain`, client-side,
   capped at six** to preserve the current layout. Pull `limit=20` and dedupe.
   If it proves awkward in practice, revisit as a #019 amendment rather than
   working around it in the view.

---

## How

### Approach

Seven workstreams, ordered so each is independently reviewable. WS1 is a
prerequisite for everything; WS3–WS6 are independent of each other.

**WS1 — Routing shell + API client.**
- `web/src/lib/router.ts`: `useRoute()` (reads `location.pathname`, subscribes
  to `popstate`) and `navigate(path)` (`history.pushState` + a synthetic
  update) — in-repo, no new dependency (OQ1). Routes: `/` (Home), `/progreso`,
  `/historial`, `/ajustes`; anything else falls back to Home. `App.tsx` switches
  on it, keeping the live session as in-app state layered over `/`, never a URL
  (OQ2), with one pushed history entry so Back exits the session cleanly.
- `web/src/lib/api.ts`: `apiGet<T>(path, signal)` — same-origin `fetch` (no base
  URL, exactly as `lib/health.ts:24` does), `Authorization: Bearer` from
  `getSessionToken()`, `401` → `clearSessionToken()` and a typed
  `UnauthorizedError` the screens translate into the Home re-prompt.
- `web/src/lib/types.ts`: TypeScript mirrors of #019's three payloads
  (`LearnerProfile`, `SessionRow`, `BandChange`), transcribed from
  `hable_ya/learner/read.py` — the field list, not a guess.
- `web/src/lib/learner.ts`: `useLearnerProfile()`, `useSessions({limit,
  offset})`, `useBandHistory()` — the `useHealth()` shape (state + `useEffect` +
  `AbortController`), each returning `{ data, error, loading }` so a screen can
  render a per-surface error without blanking.
- `web/src/lib/format.ts`: the pure helpers — `computeStreak(sessions)`,
  `formatRelative(iso)`, `formatDuration(startedAt, endedAt)` (null-safe),
  `formatMode(mode)` (the four `ConversationMode` values → Spanish labels).

**WS2 — Home goes live.** Replace the hardcoded stats array with values from
`useLearnerProfile()` + `useSessions()`; replace the hardcoded card literal with
session rows deduped most-recent-per-`theme_domain`, capped at six from a
`limit=20` pull (OQ5); wire `Progreso` / `Historial` /
`Ajustes` / avatar / "ver todo →" to `navigate()`; delete `showProximamente` and
the toast. Loading renders the existing `—` placeholders (already the visual
language for "no value"), so there is no layout shift.

**WS3 — `routes/Progreso.tsx`.** Band + calibration header, band-change
timeline from `useBandHistory()`, error and vocabulary lists from the profile
payload, and two 0–1 readouts (`l1_reliance`, `speech_fluency`). Shares Home's
visual vocabulary — serif headings, mono labels, `var(--line)` hairline grids.

**WS4 — `routes/Historial.tsx`.** Session rows from `useSessions()` with a
"cargar más" that advances `offset` by the page size. Duration from
`started_at`/`ended_at`; `mode` badge only when not `open`.

**WS5 — `routes/Ajustes.tsx`.** Health line from `useHealth()`; the María voice
card moved out of Home's right column (or duplicated — it is presentational);
token management on top of the existing `lib/token.ts` (replace / clear, with
the "solo en esta pestaña" note already used on Home). *Discovered during
exploration:* Home gates its CTA on `hasToken` regardless of server config, so
a dev running with `session_auth_disabled=true` — where `authorize_token`
returns `True` for everyone (`hable_ya/auth.py:23-24`) — must still paste a
dummy token to get past the gate. Ajustes is where that becomes visible; a
"clear token" control makes the dev loop workable either way. Not a behavior
change to auth, and not a fix to the gate.

**WS6 — Session badge + mode/topic picker.** `Session.tsx` takes the band from
the profile hook (fetched on Home, passed down, or fetched on mount with the
current `A2` as the pre-load default). `VoiceClient` gains optional
`mode`/`topic` options appended to the WS URL as query params — the server side
already parses them (`api/routes/session.py:_extract_conversation_config` →
`parse_conversation_config`, fail-safe on anything unknown) and the token
continues to ride the subprotocol, so this is a client-only change. Home gets a
compact four-chip mode selector plus an optional topic input near the CTA;
clicking a recent-topic card starts a session with that `theme_domain` as the
topic.

**WS7 — Tests + CI.** `vitest` dev dependency, a `test` script, unit tests over
`lib/format.ts` and `lib/api.ts` (pure logic only — no jsdom, no component
rendering), and a `npm test` step in the existing CI `web` job.

No Python changes are anticipated in any workstream, and **no new runtime
dependency** — the router is in-repo (OQ1) and `vitest` is dev-only (OQ4), so
`web/package.json`'s runtime deps stay `react` + `react-dom`.

### Confidence

**Level:** Medium

**Rationale:** The mechanics are High-confidence and unusually well-derisked for
this repo. The API is shipped, tested against real Postgres, and its payload
shapes are readable directly from `hable_ya/learner/read.py`; the transport path
is already open in both environments (`Caddyfile` `handle /api/*`,
`vite.config.ts` `/api` proxy); the auth model is already implemented
client-side; the mode/topic contract needs no server change. There is no new
persistence, no migration, and no new provider dependency.

What holds this at Medium is not feasibility but two things — the third,
unresolved Open Questions, was closed at approval (2026-07-25) and no longer
applies. First, this is the first spec in the series that is substantially
*design* work: three net-new screens whose layout and Spanish copy are invented
here, not derived from an existing artifact, and with no design reference the
way `Home`/`Session` came from the ported #046 designs. Second, no screen has
ever been rendered against a populated learner database, so the payloads'
*practical* sufficiency (are ten `top_vocab` lemmas interesting? does
`band_history` have enough rows to look like a timeline?) is untested — which
is what validation step 2 exists to settle before any screen is built.

Notably, unlike #016–#024, the deferred-live-spike problem mostly does **not**
apply here: `require_cloud_secrets` (`api/main.py:53`) only checks truthiness,
and the read path touches no provider, so the whole of #020 can be exercised
locally with placeholder OpenAI/Cartesia values. Only `warmup_llm` — a
1-token Anthropic ping that gates `app.state.ready` — needs a real key, and it
affects only the `/health`-driven CTA state, not any `/api/learner*` screen.

**Validate before proceeding:** (item 1 — resolving Open Questions 1–5 — was
completed at approval on 2026-07-25; the two remaining items stand.)

1. Seed a development database with a realistic spread — several sessions across
   at least two bands, one with `ended_at IS NULL`, a couple of band changes,
   and enough turns for non-empty `top_errors`/`top_vocab` — then `curl` all
   three endpoints and confirm the payloads support the screens as specced
   before building them. A script under `scripts/` or a `pytest` fixture reused
   as a seeder is fine; this is throwaway.
2. Confirm the local dev loop end to end: API booted with a real
   `ANTHROPIC_API_KEY` + placeholder OpenAI/Cartesia values, `npm run dev`, and
   an authenticated `/api/learner` response rendering in the browser. If this
   works, the remaining live-spike deferral is limited to the deployed-host
   Caddy hop.

### Key Decisions

- **Client-side derivation over new endpoints.** Streak, duration, relative
  time, and topic dedup are all computed in the browser from #019's raw rows.
  This honors #019's Open Question 4 resolution and keeps a UI presentation
  choice out of the API contract. The cost is that this logic would otherwise be
  wholly untested — which is exactly why OQ4 resolved to add Vitest for it.
- **Per-surface failure, not per-page.** Each hook owns its own error state.
  Home reads two endpoints; one failing must degrade one region. This is the
  difference between a page that looks broken and a page that looks honest.
- **Empty states are a first-class requirement, not a fallback.** The single
  most likely state of a fresh deployment is zero sessions, and the current
  screen already lies about that state (six fake topics). Every list, tile, and
  timeline specifies its empty copy.
- **The picker is client-only.** #023 deliberately shipped a fail-safe
  server-side parser: unknown mode → `open`, blank topic → `None`, never raises.
  So the picker can send anything and the handshake cannot break — which is why
  it is safe to land as the last workstream under time pressure.
- **`A2` stays as Session's pre-load default.** The band badge renders before
  the profile fetch resolves; using the existing hardcoded value as the initial
  state avoids a flash of empty chrome, and it converges to the real band within
  one request. This is the one place the old placeholder survives, deliberately.

### Testing Approach

The Python suite (469 tests, `pytest`) is untouched — no backend change is in
scope, and #019's `tests/test_learner_api.py` already covers the endpoints these
screens consume, including the fresh-DB neutral-response and `401` cases.

**Frontend unit tests** (Vitest, per OQ4) over pure logic only:

- `computeStreak` — zero sessions → 0; sessions today and yesterday → 2; two
  sessions on the same day → counts once; a gap day breaks the streak; a session
  today plus one three days ago → 1.
- `formatDuration` — normal span; `ended_at: null` → in-progress marker, never
  `NaN`; a span under a minute.
- `formatRelative` — minutes / hours / days / "hoy" boundaries.
- `formatMode` — all four `ConversationMode` values plus an unexpected string
  (the API could in principle return a value the client does not know).
- `apiGet` — attaches the Bearer header when a token is stored; omits it when
  not; a `401` clears the token and raises `UnauthorizedError`; a `503` surfaces
  as a distinguishable error; an aborted request does not set state.
- Topic dedup — most-recent-per-`theme_domain`, capped at six, in order.

**Build gate:** the existing CI `web` job (`tsc --noEmit && vite build`)
continues to gate every PR, extended with a `npm test` step.

**Manual verification checklist** against a seeded database (validation step 1
above), recorded in the decision record:

1. Fresh DB, zero sessions — Home tiles, card strip, Progreso, and Historial all
   render honest empty copy with no crash and no infinite spinner.
2. Seeded DB — band, streak, última sesión, and topic cards match the seeded
   rows; Progreso's timeline matches `band_history`; Historial paginates past
   the first page and stops cleanly at the end.
3. A session row with `ended_at IS NULL` renders as in-progress in both Home's
   cards and Historial.
4. Wrong/expired token — every screen returns to the Home token prompt and does
   not loop.
5. API stopped mid-browse — surfaces show an error, the rest of the page still
   renders, and recovery works on retry without a reload.
6. Deep-link and reload on `/progreso`, `/historial`, `/ajustes`; browser
   back/forward across all of them.
7. Start a session per mode (open / debate / role-play / interview) and from a
   topic card; confirm the resulting `sessions.mode` and `theme_domain` rows
   match what was picked. This is the one item that needs a real key set —
   deferred to a keyed host if unavailable, consistent with #016–#024.
