# hable ya — web

Voice shell for the `habla` cloud stack. Vite + React 18 + TypeScript SPA (Home +
Session screens, animated orb) that captures the mic → 16 kHz PCM → `/ws/session`
→ playback, backed server-side by `hable_ya.pipeline.serializer.RawPCMSerializer`.
The pipeline runs entirely on managed APIs (Claude / OpenAI Whisper / Cartesia) —
there is no on-device model to run.

## Prerequisites

1. The API running and reachable — locally that's `api/main.py` on
   `localhost:8000` (`docker compose up`); in prod it's the `app` service behind
   Caddy.
2. Node 20+ and `npm`.

## Dev

```bash
cd web
npm install
npm run dev
```

Then **open <http://localhost:5173/>**.

> ⚠️  Use `http://localhost:5173/`, **NOT** `http://0.0.0.0:5173/`. Chrome only
> treats `localhost` and `127.0.0.1` as secure contexts, and
> `navigator.mediaDevices.getUserMedia` is `undefined` outside a secure context.
> `vite.config.ts` pins `server.host: 'localhost'` so the dev banner won't mislead
> you, but if you paste a `0.0.0.0` URL from elsewhere, the mic will silently fail
> to initialize.

Vite proxies `/ws/session` and `/health` to `http://localhost:8000`, so no CORS
setup is needed. If the local API has `session_auth_disabled` (the dev default),
no token is required; otherwise provide one as below.

## Session token (auth)

The API gates `/ws/session` with a shared secret,
`HABLE_YA_SESSION_AUTH_TOKEN` (spec #016) — generate one with
`python -c "import secrets; print(secrets.token_urlsafe(32))"` and set it on the
API. The **same** string is what the operator pastes into the SPA.

The token is **never baked into the JS bundle** (spec #018): the served page has
no secret in it. On first load, Home shows a one-time field — paste the token and
it is kept in `sessionStorage` (this tab only, cleared on close). At connect time
`VoiceClient` offers it as the sole `Sec-WebSocket-Protocol` value; the server
reads the first offered subprotocol as the token and echoes it on accept, so the
secret never appears in a URL or access log. A rejected token (`1008`) is dropped
so the field re-appears.

## Build

```bash
npm run build      # tsc --noEmit + vite build → dist/
npm run typecheck  # tsc --noEmit only
```

## Prod serving

The SPA is **not** served by the API. `web/Dockerfile` is a two-stage build (Node
build → `caddy:2`) that bakes `dist/` into a Caddy image at `/srv`; `release.yml`
publishes it to GHCR as `<repo>-web`. The prod overlay
(`docker-compose.prod.yml`) runs that image as the `caddy` service and mounts the
repo `Caddyfile`, which routes:

- `/ws/session*` and `/health` → `reverse_proxy app:8000`
- everything else → the static SPA, with a `try_files … /index.html` history-API
  fallback so client-side routes don't 404.

Because the routes use mutually-exclusive `handle` blocks, the static file server
can never shadow the WebSocket upgrade or the health probe. `defaultWsUrl()`
derives `wss://$DOMAIN/ws/session` from `location`, so a page served at
`https://$DOMAIN/` connects with no per-host config.

## Scope

This shell is deployability + auth only. **Out** (deferred): captions, recap
screen, profile screen, orb variants B/C, tweaks panel, learner adaptation,
mobile layouts, multi-user accounts. Home's stats/topics/name are static
placeholders pending the learner-model specs.

## Related

- `web/spike/` — the validation spike that unblocked the protocol decision. Still
  useful for isolated debugging of the mic → pipeline → playback loop. Served at
  `/spike/index.html` in dev.
- `hable_ya/pipeline/serializer.py::RawPCMSerializer` — the server-side serializer
  that reads the browser's raw PCM frames.
- `api/routes/session.py::_extract_token` — the server side of the token contract.
