# Spec: Learner-Progress Read API

| Field | Value |
|---|---|
| id | 019 |
| status | approved |
| created | 2026-07-12 |
| approved | 2026-07-12 |

---

## Why

The learner model is fully **written** but has no **read** path into the
product. Every native `log_turn` tool call runs a per-turn Postgres transaction
(a `turns` row, `error_counts`, spaCy-lemmatized `vocabulary_items`, and AGE
graph upserts); `end_session` runs real placement/leveling that writes
`band_history` audit rows and updates `learner_profile.band`. The system prompt
is rebuilt each session from this stored state once the learner is calibrated.

None of it is observable outside the runtime. The only endpoints that expose
learner state — `/dev/learner` and `/dev/observations` — are mounted **only**
when `dev_endpoints_enabled` is true (`api/main.py:141`), are unauthenticated,
and are explicitly "do not use in production" (`api/main.py:144`). So on a
deployed host the frontend has no way to read the learner's band, history, or
progress. This is why the app *feels* like it neither logs sessions nor adapts:
the loop runs, but nothing surfaces it.

This spec adds authenticated production HTTP endpoints that expose the existing
learner state read-only. It is the data bridge every stalled frontend surface
in #020 depends on.

### Consumer Impact

- **The `web/` SPA (#020) is the direct consumer.** Home's stats tiles (racha /
  nivel actual / última sesión), the recent-topics cards, and the Session level
  badge are static placeholders today (`Home.tsx`, `Session.tsx`) precisely
  because there is no endpoint to read from. This spec gives them a JSON source.
  #020 does the wiring; #019 is the API contract it builds against.
- **The learner** (single-tenant, the one person the deployment serves)
  indirectly benefits: after #020 consumes this API they can finally *see* their
  CEFR band, session history, and progression — the payoff for a learner model
  that already runs but has been invisible.
- **The operator** gets a production-safe inspection surface that does not
  require flipping on the blanket-open `/dev/*` endpoints.

### Roadmap Fit

- **Depends on #016** (session auth): reuses the shared-secret token contract
  and the fail-closed authorization posture. No new auth scheme is introduced.
- **Depends on the learner model** (ported specs #029/#049, already implemented
  here): the tables, `LearnerProfileRepo`, and leveling writes this API reads
  all exist.
- **Blocks #020** (frontend surfaces): #020 cannot render progress/history/stats
  without this. Suggested order in the audit was #019 → #020.
- **Independent of #021/#022.** #021 (learner identity) may later add a name
  field to the profile payload, but that is additive and not required here.

---

## What

### Acceptance Criteria

- [ ] A production-mounted (not dev-gated) HTTP router exposes read-only learner
  state, authenticated with the existing shared-secret token, fail-closed.
- [ ] `GET /api/learner` returns the profile snapshot: `band`,
  `sessions_completed`, `l1_reliance`, `speech_fluency`, `error_patterns`,
  `vocab_strengths`, `is_calibrated`, `stable_sessions_at_band`,
  `last_band_change_at`, plus `top_errors`, `top_vocab`, and
  `recent_theme_domains` — the fields `/dev/learner` already assembles.
- [ ] `GET /api/learner/sessions?limit=&offset=` returns a paginated session
  history: for each session `session_id`, `started_at`, `ended_at`,
  `theme_domain`, `band_at_start`, and `turn_count`, newest first.
- [ ] `GET /api/learner/band-history?limit=` returns band-change audit rows:
  `from_band`, `to_band`, `reason`, `signals`, `changed_at`, newest first.
- [ ] Every endpoint returns `401` when the token is missing or wrong, and
  returns data only when a valid token is presented (or when auth is disabled
  for local dev, mirroring the WS gate).
- [ ] With auth configured but no learner activity yet (fresh DB), endpoints
  return well-formed neutral responses (`A2`, empty lists) — never a 500.
- [ ] When the DB pool is not ready, endpoints return `503`, not a crash
  (matching `/dev/learner`'s current posture).
- [ ] The shared-secret authorization check is factored into one helper used by
  both the WS endpoint and this HTTP router (no duplicated compare-digest
  logic), and the SQL read logic is factored so `/dev/learner` and the
  production endpoints do not duplicate queries.
- [ ] Endpoints are reachable from the deployed SPA's origin (served same-origin
  behind the existing prod Caddy; the read paths are reverse-proxied like
  `/ws/session` and `/health`).

### Non-Goals

- **No write/mutation endpoints.** Read-only. Band changes, session creation,
  and turn logging stay owned by the runtime pipeline.
- **No multi-user / per-learner routing.** Single-tenant `id = 1` is unchanged;
  the schema `CHECK (id = 1)` stays. Multi-user is #021's decision, not this
  spec's.
- **No new frontend UI.** Wiring the SPA to this API is #020. This spec ships the
  API and its tests only.
- **No AGE graph reads.** The knowledge graph read path is #022. This API reads
  the relational tables exclusively (as all runtime adaptivity already does).
- **No token-cost / observability metrics.** That is #014. `/dev/observations`
  (sink counters) stays dev-only and out of scope here.
- **No streak/derived-analytics computation** beyond what the raw session list
  supports (see Open Questions).

### Open Questions

All resolved at approval (2026-07-12) — the recommended default was accepted in
each case.

1. **HTTP token transport.** **Resolved: `Authorization: Bearer <token>`.**
   Standard, stays out of URLs and access logs, and the SPA already holds the
   token in `sessionStorage` from #018. The `?token=` query param the WS gate
   accepts is rejected for HTTP because it leaks into proxy logs.
2. **URL prefix.** **Resolved: `/api/learner*`.** Cleanly separates JSON reads
   from `/ws/session` + `/health` and gives Caddy one prefix to reverse-proxy.
3. **CORS.** **Resolved: no CORS middleware; route via proxy in both prod and
   dev.** In prod the SPA is served same-origin behind Caddy (#018), so no
   cross-origin surface is opened on the API; dev (Vite `:5173` → API `:8000`)
   uses a Vite dev-server proxy for `/api`.
4. **Server-side streak.** **Resolved: deferred.** Home's "racha" tile is
   computed client-side from the sessions list; revisit only if #020 finds it
   awkward.
5. **Retire vs. keep `/dev/learner`.** **Resolved: keep it**, re-pointed at the
   extracted read module so it can't drift from the production endpoints (it also
   surfaces `recent_turn_bands`, a debugging convenience the prod API omits).

---

## How

### Approach

**New router — `api/routes/learner.py`**, mounted unconditionally in
`api/main.py` next to `health_router` and `session_router` (not behind
`dev_endpoints_enabled`). Three GET endpoints under an `/api/learner` prefix,
each guarded by an auth dependency.

**Auth.** Extract the shared-secret comparison currently in
`api/routes/session.py:75` (`_authorized`) into a reusable helper — e.g.
`hable_ya/auth.py::authorize_token(settings, presented) -> bool` — keeping the
`session_auth_disabled` dev opt-out and the fail-closed "no secret configured →
reject" behavior. `session.py` re-imports it (no behavior change to the WS gate).
Add a FastAPI dependency `require_api_token` that reads the `Authorization:
Bearer <token>` header, calls `authorize_token`, and raises `401` on failure.
The WS path keeps its subprotocol/`?token=` extraction; only the HTTP path uses
the Bearer header.

**Read logic.** The queries in `api/routes/dev.py:44-160` (`get_learner`) are
the reference implementation for the profile payload. Factor the DB reads into a
read module — extend `LearnerProfileRepo` and/or add a small
`hable_ya/learner/read.py` with:
- `profile_payload(pool)` → the `/api/learner` body (reuses
  `LearnerProfileRepo.get`, `is_calibrated_async`, the `error_counts` /
  `vocabulary_items` / `sessions` / `band_history` reads already in `dev.py`).
- `session_history(pool, limit, offset)` → **new query**: `sessions` LEFT JOIN a
  per-session `COUNT(*)` over `turns`, ordered `started_at DESC`, paginated.
  This is the only genuinely new SQL (indexes already exist:
  `turns_session_idx`, and `sessions` is small).
- `band_history(pool, limit)` → the `band_history` read already in `dev.py`,
  with the `_signals_to_dict` JSONB decode helper moved alongside it.

`api/routes/dev.py::get_learner` is then re-pointed at `profile_payload` +
`band_history` so the dev and prod surfaces share one source of truth.

**Serving.** Add the `/api/*` prefix to the prod `Caddyfile` `reverse_proxy`
block (same treatment as `/ws/session` + `/health`) so the deployed SPA reaches
it same-origin. Add a Vite dev-server proxy entry for `/api` so local `npm run
dev` works cross-port without CORS. No server-side CORS middleware.

Data-shape note: `asyncpg` returns JSONB (`band_history.signals`) as a string
without a registered codec — the existing `_signals_to_dict` decode
(`dev.py:163`) must travel with the extracted query. Timestamps are serialized
as ISO-8601 strings (as `dev.py` already does).

### Confidence

**Level:** High

**Rationale:** The data layer, the auth pattern, and a near-complete reference
implementation of the largest endpoint (`/dev/learner`) all already exist and
run in production paths. The work is (a) promoting/authing an existing read,
(b) one new aggregate query (`session_history`), and (c) refactoring shared
logic out of two call sites. No new storage, no schema change, no new
dependency. The only genuinely new code is the session-history query and the
Bearer-auth dependency, both standard.

The residual uncertainty is entirely in the Open Questions (transport, prefix,
CORS/proxy) — product/routing decisions, not technical risk — and each has a
recommended default. No spike is required; the questions can be resolved in
review.

### Key Decisions

- **Reuse the #016 shared secret rather than introduce per-user auth.** Keeps the
  deployment single-tenant and the token model singular (one secret gates both
  the WS session and the read API). Multi-user auth is deferred to #021.
- **Bearer header for HTTP, not `?token=`.** Avoids leaking the secret into proxy
  access logs — the same reasoning #018 used to choose the WS subprotocol over a
  query param.
- **Same-origin serving, no CORS.** Leans on #018's Caddy edge so no
  cross-origin surface is opened on the API. Dev uses a Vite proxy.
- **Read-only, relational-only.** Consistent with the fact that all live
  adaptivity is already relational; the graph read path stays #022.

### Testing Approach

Per OVERVIEW's suite (pytest + `pytest-asyncio`, DB-marked tests run when the
`db` service is up; CI-scoped ruff + mypy over `api/` and `hable_ya/`):

- **Auth (no DB needed):** `401` on missing header, `401` on malformed
  `Authorization`, `401` on wrong token, `200` on correct token; fail-closed when
  `session_auth_token` is unset and `session_auth_disabled` is false; bypass when
  `session_auth_disabled` is true. Assert the token is never echoed in responses
  or logs.
- **Shared-helper regression:** a test that `authorize_token` produces the same
  verdicts the WS `_authorized` did, so extracting it did not change the gate.
- **`GET /api/learner` (DB):** shape assertion over all documented fields; neutral
  response on a fresh seeded DB (`band == "A2"`, empty error/vocab lists,
  `is_calibrated == false`); populated response after ingesting a few turns +
  a placement, asserting `is_calibrated` flips and top errors/vocab appear.
- **`GET /api/learner/sessions` (DB):** `turn_count` matches the number of
  ingested turns per session; ordering newest-first; `limit`/`offset` pagination;
  empty list on a fresh DB.
- **`GET /api/learner/band-history` (DB):** returns placement + leveling rows in
  reverse-chronological order; `signals` decoded to an object, not a string;
  empty list before any placement.
- **`503` when the pool is absent** (mirror the `/dev/learner` guard test).
- Reuse the existing DB test fixtures/helpers that back the current learner-model
  and `/dev/learner` tests rather than standing up new scaffolding.
