# Spec: Web Frontend Auth + Deploy

| Field | Value |
|---|---|
| id | 018 |
| status | in-progress |
| created | 2026-07-10 |

> **Open Questions resolved (2026-07-10, operator = recommended options):**
> **OQ1** → Option B (paste-once token in `sessionStorage`, never bundled) + the
> **`Sec-WebSocket-Protocol` subprotocol** transport (no `?token=`;
> `token_urlsafe` chars are valid subprotocol tokens). **OQ2** → Option A (Caddy
> `file_server` serves `dist/`; `/ws/session*` + `/health` stay reverse-proxied
> via mutually-exclusive `handle` blocks). **OQ3** → a custom Caddy+SPA image
> (`web/Dockerfile`) built + pushed by `release.yml` as `<repo>-web`. **OQ4** →
> confirmed no hardcoded `localhost`; `defaultWsUrl()` derives `wss://` from
> `location`. No server-side change.

---

## Why

The repo ships a working browser client — `web/`, a Vite + React 18 + TypeScript
SPA (Home + Session screens, the animated orb, and the mic → 16 kHz PCM →
`/ws/session` → playback loop backed by `RawPCMSerializer`). But it is a
**dev-loop artifact that predates the cloud deployment**, and nothing exposes it
to a real user. Three concrete gaps make it unusable on a deployed host:

1. **It is not built or served by the deployment.** No `Dockerfile`,
   `docker-compose*.yml`, `Caddyfile`, or CI step references `web/`. #017
   explicitly listed "No frontend build/deploy — `web/` is served separately and
   stays excluded from the API image" as a Non-Goal. The prod stack terminates
   `wss://`/`https://` at Caddy and reverse-proxies `app:8000`, which serves only
   `/ws/session` + `/health` (no `StaticFiles` mount). A deployed `habla` is
   API-only; there is no page to open.
2. **It cannot authenticate.** #016 made `/ws/session` **fail-closed**, requiring
   `HABLE_YA_SESSION_AUTH_TOKEN` via a `?token=` query param or a
   `Sec-WebSocket-Protocol` subprotocol (`api/routes/session.py::_extract_token`).
   The client opens a bare `new WebSocket(this.wsUrl)`
   (`web/src/voice/client.ts:125`) with no token, so every connection is closed
   with `1008 unauthorized`. The frontend was built (spec #046, carried over from
   `hable-ya`) before #016 added auth and was never updated.
3. **Its docs describe the deleted on-device stack.** `web/README.md` lists
   prerequisites like "llama.cpp running with the Gemma model" and "spec 021" —
   the pre-cloud world. It is actively misleading.

This spec closes the two hard blockers (serve the built SPA behind Caddy; wire
the session token) so a deployed `habla` presents a usable voice UI, and refreshes
the stale frontend docs. It does **not** expand the product surface of the UI.

### Consumer Impact

Two consumers:

- **The operator** (single-tenant deployer) gains a real front door: after
  deploying, visiting `https://$DOMAIN/` loads the voice UI instead of a bare
  WebSocket endpoint. Serving and TLS are handled by the same Caddy already in the
  prod overlay; no new infra service.
- **The learner** (end user) can actually use the product from a browser: open the
  page, grant mic, start a session, and have it connect (authenticated) rather than
  being silently rejected with `1008`.

The local dev loop (`npm run dev` → Vite on `:5173`, proxying to `:8000`) is
preserved for frontend iteration.

### Roadmap Fit

First item **after** the #001–#017 cloud-migration + deployment-readiness arc. It
picks up the frontend that #017 deliberately deferred, now that #016 (auth) and
#017 (TLS/Caddy, GHCR image) exist to build on. It depends on #016 (the token
contract it must satisfy) and #017 (the Caddy service it hangs the static site
off). It is orthogonal to the still-planned **#014** (resilience/cost) — this spec
touches neither retry/backoff nor cost metering.

---

## What

### Acceptance Criteria

From the operator's / learner's perspective:

- [ ] **Served in prod.** After `docker compose -f docker-compose.yml -f
  docker-compose.prod.yml up`, an HTTP GET of `https://$DOMAIN/` returns the built
  SPA (200, `index.html` + hashed assets), and its `/pcm-worklet.js` +
  `/public` assets load. SPA deep-link routes (`/`, `/session`) resolve to
  `index.html` (history-API fallback), not 404.
- [ ] **Authenticated session.** From the served page, starting a session opens
  `wss://$DOMAIN/ws/session` **with the session token attached** and is *accepted*
  (not closed `1008`); one full STT→Claude→Cartesia turn round-trips spoken
  Spanish. The token reaches the server by the mechanism #016 already accepts
  (`?token=` or subprotocol) with **no server-side change** to `_extract_token`.
- [ ] **Token not hardcoded in the repo.** The token is supplied at deploy time
  (build-arg/env or runtime-entered — see Open Question 1), never committed. `git
  grep` finds no literal token in `web/`.
- [ ] **`/ws/session` and `/health` still reachable** through the same Caddy host
  as before (the static site must not shadow the WebSocket upgrade or the health
  path).
- [ ] **Local dev unchanged.** `cd web && npm run dev` still serves the SPA on
  `http://localhost:5173/` proxying `/ws/session` + `/health` to `:8000`; the
  base `docker compose up` stack is untouched.
- [ ] **Build in CI/image path.** The production SPA is built (`npm run build`,
  which is `tsc --noEmit && vite build`) as part of the deploy artifact pipeline —
  either baked into an image or produced by the release workflow — so the operator
  does not hand-build `dist/` on the host. `npm run typecheck` is green.
- [ ] **Docs refreshed.** `web/README.md` describes the cloud stack (no
  llama.cpp/Gemma/spec-021 prerequisites), documents how the token is provided,
  and how the SPA is served in prod. `ROADMAP.md` gains the #018 row.

### Non-Goals

- **No new UI surface.** Explicitly out (unchanged from #046's deferred list):
  captions, recap screen, profile screen, orb variants B/C, tweaks panel, learner
  adaptation, mobile layouts. This spec makes the *existing* Home+Session shell
  deployable and authenticated — nothing more.
- **Not multi-user auth.** No login/accounts/sessions-per-user. The single shared
  `HABLE_YA_SESSION_AUTH_TOKEN` (single-tenant posture) is the only credential;
  this spec only *transports* it from browser to server.
- **Not #014.** No client-side retry/backoff, cost display, or health-driven UI
  beyond the existing health-aware CTA. Resilience/cost stays #014.
- **No SSR / Next.js / meta-framework migration.** It stays a static Vite SPA.
- **No CDN / separate frontend host.** Served from the same single host behind the
  existing Caddy — no S3/CloudFront/Vercel.

### Open Questions

1. **How the browser obtains the token (the central design decision).** The page
   is served publicly, so anything baked into the JS bundle is readable by anyone
   who loads it.
   - *Option A — build-time env (`VITE_SESSION_TOKEN`) baked into the bundle.*
     Simplest; zero UX. But the token is visible in the served JS, degrading it
     from a secret to a speed bump. Mitigated by #016's single-active-session cap
     (cost-DoS is bounded to one concurrent session regardless), but still means
     "anyone with the URL can start a session."
   - *Option B — the UI prompts the operator to paste the token* (stored in
     `sessionStorage`), keeping it out of the bundle and the served HTML. True
     shared-secret; one extra paste step on first load. **Recommended** for a
     public URL. Reduces to A's posture only if the operator chooses to hardcode.
   - *Transport sub-question:* `?token=` (simplest, but the token appears in
     access logs / `Referer`) vs. `Sec-WebSocket-Protocol` subprotocol (kept out
     of URLs/logs; the server already echoes it). Lean **subprotocol** to avoid
     logging the token; confirm Caddy forwards the header (it forwards
     `Sec-WebSocket-Protocol` transparently).
2. **Where the SPA is served from.**
   - *Option A — Caddy serves `dist/`* via `file_server` + `try_files` SPA
     fallback, with `/ws/session` + `/health` still `reverse_proxy`'d to `app`.
     Keeps the app image unchanged; `dist/` is a build artifact mounted or COPYed
     into the Caddy container. **Recommended** — clean separation, no Python
     `StaticFiles`, no app-image bloat.
   - *Option B — FastAPI `StaticFiles` mount* serving `dist/` from the app
     container. Single origin, but couples the frontend build into the API image
     (a Node build stage) and mounts static-file serving into the ASGI app.
3. **Where the build runs.** A Node stage in a (new or existing) image build, vs.
   a `build-web` job in `release.yml` that publishes `dist/` as an artifact / into
   the Caddy image. Ties to Open Question 2.
4. **Prod `wss://` URL derivation.** `client.ts::defaultWsUrl()` already derives
   `wss://` from `location.protocol`/`location.host`, so a page served at
   `https://$DOMAIN/` should Just Work — **confirm** no hardcoded `localhost`
   sneaks in via the token/transport change.

---

## How

### Approach (proposed — pending Open Questions)

Three small workstreams:

**1. Token transport in the client.**
Extend `VoiceClient` (`web/src/voice/client.ts`) to attach the session token when
opening the socket — via the `Sec-WebSocket-Protocol` subprotocol
(`new WebSocket(url, [token])`) to match `_extract_token`'s subprotocol branch
without logging it, or `?token=` as the fallback. Source the token per Open
Question 1 (recommended: a paste-once field persisted to `sessionStorage`, read at
`connect()`). No server change — `api/routes/session.py` already accepts both
mechanisms.

**2. Serve the built SPA behind Caddy (prod overlay).**
Recommended (Open Question 2A): add a `file_server` root + SPA `try_files`
fallback to the `Caddyfile`, keeping `reverse_proxy app:8000` for `/ws/session`
and `/health` (path-matched so the WS upgrade and health path are not shadowed by
the static handler). Produce `dist/` via `npm run build` in the deploy pipeline
(Open Question 3) and make it available to the Caddy container (COPY into a small
custom Caddy image, or a mounted volume). Base `docker-compose.yml` and the local
`npm run dev` loop are untouched.

**3. Docs.**
Rewrite `web/README.md` for the cloud stack (drop llama.cpp/Gemma/spec-021; add
the token-provision step and the prod serving model). Add the #018 ROADMAP row +
revision-history entry.

### Confidence

**Level:** Medium

**Rationale:** The client-side token attach and a Caddy `file_server` + SPA
fallback are both standard and low-risk, and `defaultWsUrl()` already handles the
`wss://` derivation. What holds this at Medium is (a) the **token-exposure design
decision** (Open Question 1) is a genuine security-posture choice, not a mechanical
one, and should be operator-confirmed before implementation; (b) getting Caddy to
serve static SPA routes **without shadowing** the WebSocket upgrade or `/health`
needs a live check (path matcher ordering); and (c) the build/serve wiring (Open
Question 2/3) crosses the image + CI boundary and must be exercised end-to-end, not
assumed. None are deep unknowns.

**Validate before proceeding:**
- Confirm Open Question 1 (token exposure model) and Open Question 2 (serve
  location) with the operator — these gate the implementation shape.
- Spike: served page over `wss://` through Caddy drives one full authenticated
  turn (reuse #016's session over TLS).
- Spike: `curl https://$DOMAIN/` returns the SPA **and** a `wss://$DOMAIN/ws/session`
  upgrade still succeeds from the same host (no handler shadowing).

### Key Decisions (proposed)

- **Transport the token, don't rebuild auth.** #016's contract is sufficient; this
  spec only carries the existing shared secret from browser to server. No new
  server-side auth code.
- **Serve via Caddy, not FastAPI.** Keep static serving out of the ASGI app and the
  API image lean (mirrors #017's "keep the image lean" posture); the prod Caddy is
  already the TLS edge.
- **Prod-overlay only.** Static serving lives in the prod `Caddyfile`/overlay; the
  base compose file and the `npm run dev` proxy loop stay exactly as they are.
- **No UI scope creep.** Deployability + auth only; the deferred #046 screens stay
  deferred.

### Testing Approach

- **Client unit/typecheck.** `npm run typecheck` green; a unit test (or manual
  harness) asserting the token is attached to the socket handshake in the chosen
  transport.
- **Build gate.** `npm run build` succeeds and emits `dist/`; `docker compose -f
  docker-compose.yml -f docker-compose.prod.yml config` still parses with the
  static-serving addition.
- **Serve + upgrade spike.** `GET /` returns the SPA; `/ws/session` upgrade and
  `/health` still resolve through Caddy (no shadowing).
- **Authenticated turn spike.** From the served page, one full STT→Claude→Cartesia
  turn over `wss://` with the token accepted (not `1008`).
- **Local loop regression.** `npm run dev` still serves and proxies to `:8000`;
  base `docker compose up` unaffected.
