"""Browser checks for the learner's name on screen (spec #021).

These exist because the acceptance criteria they cover cannot be settled any
other way. "Sees a blank avatar circle", "shows the new name without a manual
reload" and "40 characters fits the greeting" are claims about rendered layout
and client-side navigation — a unit test over `greetingLine` cannot observe
any of them, and #021 shipped with a real defect in the third because the
check was skipped.

That defect is instructive and is pinned below: OQ3 justified the 40-character
bound as fitting the hero "without wrapping past two lines at the SPA's
`maxWidth: 520`". `maxWidth: 520` is on the paragraph *beneath* the hero, not
the `<h1>`. A 40-character name rendered five lines and pushed the CTA off
screen, while every acceptance criterion and every unit test still passed.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.harness import HarnessServer

pytestmark = pytest.mark.e2e

#: Exactly 40 characters — the bound `normalize_display_name` enforces.
LONG_NAME = "Maximiliana Guadalupe Fernández Ochoa Ru"

#: The fabricated name #021 removed. It must never come back.
FABRICATED = "Ana"


async def _hero(page: Any) -> str:
    return str(await page.locator("h1").first.inner_text())


async def _avatar(page: Any) -> str:
    return str(await page.locator("div[title='Ajustes']").inner_text())


async def _open(page: Any, harness: HarnessServer, path: str = "/") -> None:
    await page.goto(f"{harness.base_url}{path}", wait_until="networkidle")
    await page.wait_for_selector("h1")


async def test_no_name_claims_nothing(
    page: Any, harness: HarnessServer, set_display_name: Any
) -> None:
    await set_display_name(None)
    await _open(page, harness)

    hero = await _hero(page)
    avatar = await _avatar(page)

    assert FABRICATED not in hero, f"the placeholder name is back: {hero!r}"
    assert "null" not in hero and "undefined" not in hero, hero
    # Capitalized and terminated, with no comma left dangling where the name
    # would have gone.
    assert hero.strip()[0].isupper(), hero
    assert hero.strip().endswith("."), hero
    assert "," not in hero, f"stray comma with no name: {hero!r}"
    assert avatar.strip() == "", f"avatar should be blank, got {avatar!r}"
    assert page.console_errors == []


async def test_blank_avatar_still_navigates(
    page: Any, harness: HarnessServer, set_display_name: Any
) -> None:
    # An empty circle still has to be a control — it is the only route to the
    # screen where the name is set.
    await set_display_name(None)
    await _open(page, harness)

    await page.locator("div[title='Ajustes']").click()
    await page.wait_for_url("**/ajustes")
    assert page.url.endswith("/ajustes")
    assert page.console_errors == []


async def test_name_renders_in_hero_and_avatar(
    page: Any, harness: HarnessServer, set_display_name: Any
) -> None:
    await set_display_name("Ángela")
    await _open(page, harness)

    assert "Ángela" in await _hero(page)
    # First code point, uppercased — not a split surrogate, not an ASCII fold.
    assert (await _avatar(page)).strip() == "Á"
    assert page.console_errors == []


async def test_saving_in_ajustes_reaches_home_without_a_reload(
    page: Any, harness: HarnessServer, set_display_name: Any
) -> None:
    # Imported here, not at module scope: this file is collected on every
    # `pytest` run, including on machines without the `e2e` extra, where a
    # top-level playwright import would be a collection error rather than the
    # skip the conftest promises.
    from playwright.async_api import expect

    await set_display_name(None)
    await _open(page, harness, "/ajustes")

    await page.get_by_placeholder("Sin nombre").fill("Ángela")
    await page.get_by_role("button", name="Guardar").first.click()
    await page.wait_for_selector("text=guardado")

    # Client-side navigation only. If the document reloaded, the assertions
    # below would still pass on a refetch — so check the timer origin too.
    before = await page.evaluate("performance.now()")
    await page.get_by_text("hable ya").first.click()
    await page.wait_for_url(f"{harness.base_url}/")

    # Retrying assertions, not a sleep: Home mounts with the profile fetch
    # still in flight, so the hero is legitimately name-less for a beat. The
    # criterion is that it arrives without a reload, not that it is instant.
    await expect(page.locator("h1").first).to_contain_text("Ángela")
    await expect(page.locator("div[title='Ajustes']")).to_have_text("Á")

    assert await page.evaluate("performance.now()") > before, (
        "the document reloaded; this no longer tests live propagation"
    )
    assert page.console_errors == []


async def test_a_maximum_length_name_keeps_the_cta_on_screen(
    page: Any, harness: HarnessServer, set_display_name: Any
) -> None:
    assert len(LONG_NAME) == 40
    await set_display_name(LONG_NAME)
    await _open(page, harness)

    h1 = page.locator("h1").first
    box = await h1.bounding_box()
    line_height = await page.evaluate(
        "el => parseFloat(getComputedStyle(el).lineHeight)",
        await h1.element_handle(),
    )
    lines = round(box["height"] / line_height)

    assert lines <= 2, (
        f"hero wrapped to {lines} lines with a {len(LONG_NAME)}-character name"
    )
    # Greeted by first name; the full value still lives in Ajustes.
    assert "Maximiliana" in await _hero(page)

    cta = await page.get_by_text("Empezar a hablar").first.bounding_box()
    assert cta["y"] < 900, f"CTA pushed to {cta['y']:.0f}px, below the fold"
    assert page.console_errors == []


async def test_ajustes_shows_the_whole_stored_name(
    page: Any, harness: HarnessServer, set_display_name: Any
) -> None:
    # The hero abbreviates; the field the learner edits must not.
    await set_display_name(LONG_NAME)
    await _open(page, harness, "/ajustes")

    assert await page.get_by_placeholder("Sin nombre").input_value() == LONG_NAME
    assert page.console_errors == []
