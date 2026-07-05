# hable ya — web

Voice shell for spec [046](../docs/specs/046-web-frontend-voice-shell/spec.md). Vite + React 18 + TypeScript SPA that ports the Home and Session screens from `docs/artifacts/hable-ya/project/` and wires Session to the `/ws/session` voice pipeline from spec 021.

## Prerequisites

1. `llama.cpp` running with the Gemma model (see repo `OVERVIEW.md`).
2. `api/main.py` running on `localhost:8000` (voice pipeline from spec 021).
3. Node 18+ and `npm`.

## Dev

```bash
cd web
npm install
npm run dev
```

Then **open <http://localhost:5173/>**.

> ⚠️  Use `http://localhost:5173/`, **NOT** `http://0.0.0.0:5173/`. Chrome only treats `localhost` and `127.0.0.1` as secure contexts, and `navigator.mediaDevices.getUserMedia` is `undefined` outside a secure context. `vite.config.ts` pins `server.host: 'localhost'` so the dev banner won't mislead you, but if you paste a `0.0.0.0` URL from elsewhere, the mic will silently fail to initialize.

Vite proxies `/ws/session` and `/health` to `http://localhost:8000`, so no CORS setup is needed.

## Build

```bash
npm run build      # tsc --noEmit + vite build
npm run typecheck  # tsc --noEmit only
```

## Scope for this slice (#046)

- **In:** Home (static placeholder data for persistence-bound fields), Session wired to a real `/ws/session`, halo-variant orb, health-aware CTA, pause/close, error banner on unexpected WS close.
- **Out:** captions, recap screen, profile screen, orb variants B/C, tweaks panel, learner adaptation, mobile layouts, auth.

See the spec for the full acceptance criteria and deferred items.

## Related

- `web/spike/` — the validation spike that unblocked the protocol decision. Still useful for isolated debugging of the mic → pipeline → playback loop. Served at `/spike/index.html` in dev.
- `hable_ya/pipeline/serializer.py::RawPCMSerializer` — the server-side serializer that makes `/ws/session` actually read the browser's raw PCM frames.
