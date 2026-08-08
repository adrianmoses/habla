"""Fixtures for the browser checks.

Every test here is marked `e2e` and deselected by default (`addopts` in
pyproject), because unlike the rest of the suite these need three things a
developer may not have to hand: the `e2e` extra, a downloaded chromium, and a
built `web/dist`.

Missing any of those **skips** with a reason, matching how `tests/conftest.py`
skips when Postgres is unreachable — a developer running `pytest -m e2e` on a
fresh checkout gets told what to install, not a stack trace. But a skip in CI
would be a green check that verified nothing, so setting
`HABLE_YA_E2E_REQUIRED=1` turns every one of those skips into a failure. CI
sets it.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from tests.e2e.harness import DIST, E2E_TOKEN, HarnessServer

VIEWPORT = {"width": 1440, "height": 900}
SCREENSHOTS = Path(__file__).parent / "screenshots"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: object) -> Any:
    """Expose each phase's result so fixtures can see whether the test failed.

    Standard pytest recipe. Used only to decide whether to keep a screenshot —
    a failing *visual* assertion is close to undebuggable from a CI log alone.
    """
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"report_{report.when}", report)


def _missing(reason: str) -> None:
    """Skip, unless CI has declared these checks mandatory."""
    if os.environ.get("HABLE_YA_E2E_REQUIRED") == "1":
        pytest.fail(f"HABLE_YA_E2E_REQUIRED=1 but {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def playwright_available() -> None:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        _missing(
            "playwright is not installed; run `uv sync --extra e2e` "
            "then `uv run playwright install chromium`"
        )


@pytest.fixture(scope="session")
def spa_built() -> None:
    if not (DIST / "index.html").is_file():
        _missing(f"{DIST}/index.html is missing; run `cd web && npm run build`")


@pytest_asyncio.fixture(scope="session")
async def harness(
    db_pool: asyncpg.Pool, spa_built: None
) -> AsyncIterator[HarnessServer]:
    """The learner API + the built SPA, same-origin, on a free port.

    Depends on `db_pool` for ordering, not for the pool itself: that fixture is
    what repoints `settings.database_url` at `hable_ya_test` for the session,
    and the harness opens its own pool inside its own loop.
    """
    server = HarnessServer()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest_asyncio.fixture
async def page(
    request: pytest.FixtureRequest,
    harness: HarnessServer,
    playwright_available: None,
) -> AsyncIterator[object]:
    """A chromium page with the session token pre-seeded and errors collected.

    The token goes in via an init script rather than a visit-then-reload, so
    the very first render already has it — otherwise every test would first
    exercise the token-less prompt and the guaranteed 401 behind it.

    `page.console_errors` is asserted on by each test: #020's browser pass found
    defects that showed up there before they showed up in the DOM.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport=VIEWPORT)
        await ctx.add_init_script(
            f"sessionStorage.setItem('habla.sessionToken', {json.dumps(E2E_TOKEN)})"
        )
        pg = await ctx.new_page()

        errors: list[str] = []
        pg.on(
            "console",
            lambda m: (
                errors.append(f"{m.type}: {m.text}") if m.type == "error" else None
            ),
        )
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        pg.console_errors = errors  # type: ignore[attr-defined]

        try:
            yield pg
        finally:
            report = getattr(request.node, "report_call", None)
            if report is not None and report.failed:
                SCREENSHOTS.mkdir(exist_ok=True)
                await pg.screenshot(
                    path=SCREENSHOTS / f"{request.node.name}.png", full_page=True
                )
            await browser.close()


@pytest_asyncio.fixture
async def set_display_name(clean_learner_state: asyncpg.Pool) -> object:
    """Write a name straight to the profile row, bypassing HTTP.

    These tests are about what the browser *renders*; `test_learner_api.py`
    already covers what the endpoint accepts.
    """

    async def _set(value: str | None) -> None:
        async with clean_learner_state.acquire() as conn:
            await conn.execute(
                "UPDATE learner_profile SET display_name = $1 WHERE id = 1", value
            )

    return _set
