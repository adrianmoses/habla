# Decision Record: Learner-Progress Read API

| Field | Value |
|---|---|
| id | 019 |
| status | implemented |
| created | 2026-07-12 |
| spec | [spec.md](./spec.md) |

---

## Context

#019 came out of a post-deploy product audit: the deployed app *felt* like it
neither logged sessions nor adapted to the learner, even though the backend
learner loop was fully wired (every `log_turn` writes `turns` / `error_counts` /
`vocabulary_items` + AGE upserts, and `end_session` runs placement/leveling into
`band_history`). The gap was purely a missing **read** path — the only reader,
`GET /dev/learner`, was dev-gated, unauthenticated, and "do not use in
production." This feature promotes that read into an authed production API so the
frontend (#020) has a contract to render.

The spec was approved at **High** confidence with all five Open Questions
resolved to their recommended defaults. Implementation confirmed that
assessment: the largest endpoint already existed in `dev.py`, so the work was
mostly extraction + auth, and it matched the spec with no design divergences.
The one discovery worth recording is a shape subtlety in the `/dev/learner`
re-point (below).

## Decision

Shipped three authenticated, production-mounted read endpoints under
`/api/learner`:
- `GET /api/learner` — profile snapshot + top errors/vocab + recent themes
- `GET /api/learner/sessions?limit=&offset=` — paginated session history with a
  per-session `turn_count`
- `GET /api/learner/band-history?limit=` — band-change audit rows

All three are gated by the #016 shared secret via an `Authorization: Bearer`
dependency (`require_api_token`), fail-closed. Two extractions keep the code
DRY and the gate consistent: the shared-secret check moved to
`hable_ya/auth.py::authorize_token` (the WS `_authorized` now delegates to it),
and the SQL read logic moved to `hable_ya/learner/read.py`, which both the new
endpoints and the re-pointed `/dev/learner` consume. Serving is same-origin: a
`/api/*` reverse-proxy handle in the prod `Caddyfile` and a `/api` Vite dev
proxy — no CORS middleware. Read-only, single-tenant, relational-only (no AGE
reads).

---

## Alternatives Considered

### HTTP token transport (spec Open Question 1)

**Option A — `Authorization: Bearer <token>`.**
- Pros: standard; stays out of URLs and proxy access logs; the SPA already
  holds the token in `sessionStorage` from #018.
- Cons: none material for this use.

**Option B — reuse the `?token=` query param the WS gate also accepts.**
- Pros: one transport for both surfaces.
- Cons: query strings leak into reverse-proxy/access logs — the exact reason
  #018 chose the WS subprotocol over `?token=`.

**Chosen:** A. Same log-hygiene reasoning #018 applied to the WS handshake.

### Where the shared auth check lives

**Option A — extract to `hable_ya/auth.py::authorize_token`; `_authorized`
delegates.**
- Pros: one implementation gates both WS and HTTP; the WS import/signature is
  preserved so `test_session_auth.py` and the WS gate are untouched; a
  regression test pins that the two agree.
- Cons: one more module.

**Option B — import `_authorized` from `api.routes.session` into the new
router.**
- Pros: no new file.
- Cons: makes a route module depend on another route module for core auth;
  leaves the helper's home in the WS file, which is the wrong owner.

**Chosen:** A. Auth is a domain concern, not a route concern; `hable_ya/` is the
right home.

### Read-logic placement

**Option A — new `hable_ya/learner/read.py` with `profile_payload` /
`session_history` / `band_history`, consumed by both the prod router and
`/dev/learner`.**
- Pros: single source of truth; `/dev/learner` and `/api/learner` cannot drift;
  deletes ~120 lines of inline SQL from `dev.py`.
- Cons: `/dev/learner` has to re-shape the shared payload (it nests the profile
  fields under a `profile` key and adds `recent_turn_bands`).

**Option B — leave `dev.py` as-is; duplicate the queries in the new router.**
- Pros: zero change to the working dev endpoint.
- Cons: two copies of the same SQL to maintain; guaranteed drift — the spec
  called this out as a criterion.

**Chosen:** A. The spec required the read logic be factored so the two surfaces
don't duplicate queries.

### Serving / CORS (spec Open Question 3)

**Option A — same-origin behind Caddy (`/api/*` reverse-proxy handle) + a Vite
dev proxy; no CORS middleware.**
- Pros: no cross-origin surface opened on the API; reuses #018's edge; one
  prefix for Caddy to route.
- Cons: local dev must go through the Vite proxy rather than hitting `:8000`
  directly.

**Option B — add `CORSMiddleware` to the API.**
- Pros: the SPA could call the API cross-origin directly.
- Cons: opens a cross-origin surface on an authed API for no prod benefit (prod
  is same-origin anyway).

**Chosen:** A.

---

## Tradeoffs

- **One secret, one tenant.** Reusing the #016 shared secret keeps the token
  model singular but means the read API is exactly as single-tenant as the rest
  of the system — there is no per-user authorization, by design (multi-user is
  #021).
- **Coupled dev/prod shape.** `/dev/learner` now depends on `read.py`; a change
  to `profile_payload`'s keys ripples to the dev endpoint's `profile` sub-object.
  That coupling is the point (no drift), but it does mean the dev endpoint is no
  longer independently editable.
- **No CORS = dev goes through the proxy.** Slightly less convenient than a bare
  cross-origin call, traded for not opening a cross-origin surface on an authed
  endpoint.
- **Relational-only.** Consistent with the fact that all live adaptivity is
  relational; the AGE graph read path stays deferred to #022.

---

### Spec Divergence

The implementation matched the spec. No design divergences — every acceptance
criterion was built as specified, and all five Open Questions were implemented
at their approved defaults.

| Spec Said | What Was Built | Reason |
|---|---|---|
| Re-point `/dev/learner` at `profile_payload` + `band_history` | Done, with the shared payload re-shaped: profile fields nested under a `profile` key and the dev-only `recent_turn_bands` added on top | The spec anticipated this ("adds its dev-only `recent_turn_bands`"); the existing `/dev/learner` response shape (`{profile: {...}, top_errors, ...}`) had to be preserved exactly so `test_dev_endpoints.py` stayed green — a `.pop()`-and-nest, not a divergence |

---

## Spec Gaps Exposed

- **Live end-to-end check remains deferred, same class as #016/#017/#018.** The
  spec's Testing Approach and the plan's verification both list a live `curl`
  through a fully-booted app + Caddy. A full app boot fail-fasts without the
  three cloud-API keys (`require_cloud_secrets` + `warmup_llm`), so that hop was
  not exercised here. The request path *was* verified against real Postgres/AGE
  via `httpx.ASGITransport` integration tests; what stays unverified is the Caddy
  reverse-proxy hop and the lifespan-populated `app.state` on the real
  `api.main.app`. This is the same "needs real keys + a public domain" deferral
  those three specs carried — a candidate for a single consolidated deployed-host
  smoke pass rather than a per-spec gap.
- **No new roadmap items surfaced.** #020 (consume this API), #021 (identity),
  and #022 (graph reads) were already on the roadmap and are unchanged by this
  work.

---

## Test Evidence

New suite (`tests/test_learner_api.py`) — auth gate (DB-free), payload /
pagination / band-history (real Postgres via `clean_learner_state`), and the
shared-helper extraction regression:

```
$ uv run pytest tests/test_learner_api.py -q
26 passed, 1 warning in 2.50s
```

Extraction was behavior-preserving — the WS `_authorized` matrix and the
`/dev/learner` response shape both still pass unchanged:

```
$ uv run pytest tests/test_session_auth.py tests/test_dev_endpoints.py -q
17 passed, 1 warning in 2.35s
```

Full suite (DB up, so the ~52 DB-marked tests run) — no regressions:

```
$ uv run pytest -q
373 passed, 9 warnings in 16.67s
```

Lint + type gates clean on the changed paths:

```
$ uv run ruff check api/ hable_ya/ tests/test_learner_api.py
All checks passed!

$ uv run mypy api/ hable_ya/
Success: no issues found in 49 source files
```

Routing (prod edge) validated, `/api/*` handle ordered before the catch-all SPA
handler so the file_server cannot shadow it:

```
$ docker run --rm -e DOMAIN=example.com -e ACME_EMAIL=a@b.c \
    -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2 \
    caddy validate --config /etc/caddy/Caddyfile
Valid configuration
```
