# Decision Record: Web Frontend Auth + Deploy

| Field | Value |
|---|---|
| id | 018 |
| status | implemented |
| created | 2026-07-10 |
| spec | [spec.md](./spec.md) |

---

## Context

The `web/` Vite + React SPA predated the cloud deployment: a deployed `habla` was
API-only (prod Caddy just reverse-proxied `app:8000`), so there was no page to
open, and the browser client opened a **token-less** WebSocket that #016's
fail-closed `/ws/session` rejected with `1008`. This feature closes those two
blockers and refreshes the stale (llama.cpp/Gemma) frontend docs. It was the first
item after the #001–#017 cloud-migration arc, building on #016 (the token
contract) and #017 (the Caddy TLS edge / GHCR image pipeline).

The four Open Questions were resolved with the operator up front, all taking the
spec's recommended option, before implementation began.

Two things surfaced during implementation that the spec did not anticipate:

1. **The build was already broken on a fresh checkout.** `web/src/routes/Home.tsx`
   imports `useHealth` from `../lib/health`, but `web/src/lib/health.ts` was absent
   from the branch. Root cause: the repo `.gitignore` carried the standard Python
   template's bare `lib/` rule, which matches **any** nested directory named `lib`
   — so `web/src/lib/` was silently ignored and the file (health-aware CTA, #046
   scope) was never committed. `npm run build` / `typecheck` therefore failed on a
   missing module, blocking the spec's build-gate acceptance criterion. This had to
   be fixed first.

2. Because the token is transported per OQ1, a **rejected token** (`1008`) needed a
   recovery path — otherwise a wrong paste would wedge the UI on an error with no
   way to re-enter. Not called out in the spec's approach.

## Decision

Transport #016's existing shared secret from browser to server and serve the built
SPA behind the existing prod Caddy — **no server-side change**. Concretely:

- **Token (OQ1 = Option B + subprotocol):** the operator pastes the token once into
  a field on Home; it is kept in `sessionStorage` (never baked into the bundle) and
  offered as the sole `Sec-WebSocket-Protocol` value at connect. The server already
  reads the first offered subprotocol as the token and echoes it on accept
  (`api/routes/session.py::_extract_token`), so nothing on the server changed and
  the secret never appears in a URL or access log.
- **Serve (OQ2 = Option A):** the prod `Caddyfile` uses mutually-exclusive `handle`
  blocks — `/ws/session*` and `/health` reverse-proxy to `app:8000`, everything
  else is served from `/srv` with a `try_files … /index.html` SPA fallback — so the
  static file server can never shadow the WS upgrade or the health probe.
- **Build (OQ3):** `web/Dockerfile` is a two-stage build (Node → `caddy:2`) baking
  `dist/` into a Caddy image at `/srv`, published by `release.yml` as `<repo>-web`;
  the prod overlay's `caddy` service pulls it. A `ci.yml` `web` job enforces the
  build gate on PRs.

Plus the two implementation discoveries: anchor the `.gitignore` `lib/` rule to
`/lib/` (restoring `web/src/lib/health.ts`), and clear the stored token on a `1008`
close so Home re-prompts.

---

## Alternatives Considered

### OQ1 — How the browser obtains the token

**Option A — build-time `VITE_SESSION_TOKEN` baked into the bundle**
- Pros: zero UX; nothing to paste.
- Cons: the token is readable by anyone who loads the served JS — degrades a shared
  secret to a speed bump on a public URL.

**Option B — operator pastes the token once → `sessionStorage`**
- Pros: keeps the secret out of the served HTML/JS; a true shared secret; cleared
  when the tab closes.
- Cons: one extra paste step on first load.

**Chosen: B.** The page is served publicly, so a bundle-baked token is readable by
anyone with the URL. Option B keeps it a real secret for one paste of cost. (The
`?token=` vs. subprotocol sub-question resolved to **subprotocol**: it keeps the
token out of URLs / access logs / `Referer`, the server already echoes it, and
`secrets.token_urlsafe` output is a valid RFC-6455 subprotocol token — base64url
`A-Za-z0-9-_` — so no `?token=` fallback was needed.)

### OQ2 — Where the SPA is served from

**Option A — Caddy `file_server` serves `dist/`**
- Pros: keeps static serving out of the ASGI app and the API image lean; Caddy is
  already the TLS edge.
- Cons: `dist/` must be made available to the Caddy container (a custom image).

**Option B — FastAPI `StaticFiles` mount**
- Pros: single origin; no separate image.
- Cons: couples a Node build stage into the API image and mounts static serving
  into the ASGI app.

**Chosen: A.** Mirrors #017's "keep the image lean" posture; the API image and the
ASGI app are untouched.

### OQ3 — Where the build runs

**Option A — custom Caddy+SPA image built in `release.yml`**
- Pros: operator pulls a prebuilt image (consistent with #017's GHCR/pull posture);
  no hand-built `dist/` on the host.
- Cons: a second image to publish and version.

**Option B — a `build-web` job publishing `dist/` as an artifact / mounted volume**
- Pros: no second image.
- Cons: reintroduces host-side artifact wiring that #017 deliberately moved away
  from.

**Chosen: A**, following directly from OQ2 = A and the existing release pipeline.

### Rejected-token recovery (implementation-surfaced)

**Option A — leave the token in storage on `1008`**
- Cons: a wrong paste wedges the UI; the field never reappears.

**Option B — `clearSessionToken()` on a `1008` close, show a re-enter message**
- Pros: self-service recovery; Home re-prompts on return.

**Chosen: B** (`web/src/routes/Session.tsx`).

---

## Tradeoffs

- **Security posture is bounded, not absolute.** Option B keeps the token out of the
  bundle, but a single shared secret is still all that gates the endpoint — this
  spec only *transports* it (multi-user auth is an explicit Non-Goal). #016's
  single-active-session cap remains the real cost-DoS bound.
- **`sessionStorage`, not `localStorage`.** The token clears when the tab closes, so
  the operator re-pastes each session. Chosen deliberately: a public shared machine
  shouldn't persist the secret to disk. It trades convenience for a smaller blast
  radius.
- **A second image to keep in lockstep.** The web image and the app image are
  versioned independently (same tag strategy) and must be deployed together;
  neither gates the other in CI. The gain is a lean API image and a clean
  serving/app separation.
- **One field of UI was added** (the token paste) despite the "no new UI surface"
  Non-Goal. It is auth transport, not product surface — kept to a single input that
  only appears when no token is stored.

---

### Spec Divergence

The implementation matched the spec's approach. The differences below are additive —
they resolve things the spec left open or did not foresee, none reverse a spec
decision.

| Spec Said | What Was Built | Reason |
|---|---|---|
| Attach the token; no server change | Exactly that — token on the subprotocol, `_extract_token` untouched | — |
| Caddy `file_server` + SPA fallback, WS/health reverse-proxied | `handle`-block Caddyfile (mutually exclusive) rather than bare matchers | `handle` blocks guarantee no shadowing regardless of Caddy's directive auto-sort |
| Build `dist/` in the deploy pipeline | Custom Caddy image in `release.yml` **and** a `ci.yml` typecheck/build gate | The spec's build gate ("`typecheck` green") is only meaningful if enforced on PRs |
| (silent on rejected token) | `1008` close clears the stored token and re-prompts | A wrong paste would otherwise wedge the UI |
| (assumed the SPA built) | Restored `web/src/lib/health.ts` + fixed the `.gitignore` `lib/` rule | The build was already broken on fresh checkout; see Spec Gaps |

---

## Spec Gaps Exposed

1. **`.gitignore` swallowed frontend source.** The repo's bare `lib/` ignore rule
   (Python packaging template) matched `web/src/lib/`, so `health.ts` was never
   committed and the SPA build broke on a clean checkout — undetected because CI had
   no web build job until this spec. Fixed by anchoring the rule to `/lib/`. The
   spec assumed a working build as its starting point; it was not. Worth a general
   guard: the new `ci.yml` `web` job now catches a broken frontend build on any PR.
2. **The token contract needed a failure-path UX.** #016 defined how a token is
   *accepted*; neither #016 nor #018 said what the client does when it is
   *rejected*. Now handled client-side; no server change implied.

---

## Test Evidence

**Frontend build gate** — `npm run build` (`tsc --noEmit && vite build`), green;
`dist/` emits `index.html` + hashed assets (proves Step-0 restore + WS1 compile):

```
> hable-ya-web@0.0.0 build
> tsc --noEmit && vite build

vite v5.4.21 building for production...
✓ 40 modules transformed.
dist/index.html                   0.76 kB │ gzip:  0.42 kB
dist/assets/index-LLVNysuQ.css    0.99 kB │ gzip:  0.58 kB
dist/assets/index-BZELAHVJ.js   164.81 kB │ gzip: 52.89 kB
✓ built in 339ms
```

**Prod compose parses + Caddyfile valid**:

```
compose config exit=0
Valid configuration
```

**Web image builds; `/srv` holds the SPA** (`docker build ./web` → `ls /srv`):

```
drwxr-xr-x    2 root  root  4096  assets
-rw-r--r--    1 root  root   757  index.html
-rw-rw-r--    1 root  root  2322  pcm-worklet.js
```

**Routing — SPA served, deep-link fallback, and NO shadowing of WS/health.** The
image run with an HTTP mirror of the prod routing (`reverse_proxy` pointed at a dead
`127.0.0.1:9`, so a `502` proves the path routed to the proxy and was *not* served
by the static handler):

```
GET /                 status=200          # SPA
GET /session          status=200          # try_files fallback -> index.html (not 404)
GET /assets/index-*.js status=200         # hashed asset
GET /pcm-worklet.js   status=200          # public asset
GET /health           status=502          # routed to proxy, NOT static-shadowed
GET /ws/session       status=502          # routed to proxy, NOT static-shadowed
```

**Secret hygiene** — no token literal committed under `web/`:

```
no token-like literals in web/src
```

**Deferred (require a public domain + real provider keys — spec's Medium-confidence
live spikes):** the served page driving one full authenticated STT→Claude→Cartesia
turn over real `wss://` through Caddy, and the same serve-plus-upgrade coexistence
over real TLS. The local HTTP run above exercised the routing/shadowing risk; only
the TLS + live-pipeline legs remain for a human to run on a deployed host.
