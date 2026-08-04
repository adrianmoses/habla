"""Same-origin test harness: the real learner API plus the built SPA.

The browser checks need what a deployed box has — the SPA and `/api/learner*`
on one origin — without what a deployed box costs. So this mounts the *real*
`api.routes.learner` router (auth dependency and all) beside a static server
for `web/dist`, which is the arrangement `Caddyfile` produces in production
and `vite.config.ts`'s proxy fakes in development.

Two things are deliberately stubbed:

- **`/health`** returns `ok` unconditionally. The real probe gates on
  `app.state.ready`, which `api.main`'s lifespan only sets after `warmup_llm`
  pings Anthropic — real money for no signal about the greeting.
- **No `/ws/session`.** Nothing here presses the CTA; a mic permission and a
  paid socket are not part of what these checks assert.

Everything the tests actually exercise — the Bearer gate, validation, the
`PATCH`/`GET` round trip, the payload shape — is the production code path.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from api.routes.learner import router as learner_router
from hable_ya.db import close_pool, open_pool

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST = REPO_ROOT / "web" / "dist"

#: The harness' shared secret. Not a real credential — it never leaves
#: localhost and the server it authenticates lives for the test session.
E2E_TOKEN = "e2e-browser-token"


def build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        # The server thread owns its own loop, so it opens its own pool rather
        # than borrowing the test session's. `settings.database_url` is already
        # pointed at hable_ya_test by the `db_pool` fixture, so this lands on
        # the same database the tests write to.
        app.state.db_pool = await open_pool()
        try:
            yield
        finally:
            await close_pool(app.state.db_pool)

    app = FastAPI(lifespan=lifespan)
    app.state.settings = SimpleNamespace(
        session_auth_token=E2E_TOKEN, session_auth_disabled=False
    )
    app.include_router(learner_router)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "llm_backend": "stub"})

    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str) -> FileResponse:
        """Serve the file if it exists, else index.html.

        The SPA routes on the History API (`lib/router.ts`), so a deep link to
        `/ajustes` must return the app shell rather than a 404 — the same
        `try_files` behaviour the prod Caddyfile provides.
        """
        candidate = DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")

    return app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class HarnessServer:
    """uvicorn on a background thread, with its own event loop."""

    def __init__(self) -> None:
        self.port = _free_port()
        config = uvicorn.Config(
            build_app(),
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._server.serve()), daemon=True
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self, timeout: float = 30.0) -> None:
        self._thread.start()
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._server.started:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("harness server did not start")
            if not self._thread.is_alive():
                raise RuntimeError("harness server thread died during startup")
            await asyncio.sleep(0.05)

    async def stop(self) -> None:
        self._server.should_exit = True
        await asyncio.to_thread(self._thread.join, 10.0)
