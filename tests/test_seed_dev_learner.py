"""The dev seeder produces the end state its docstring promises (spec #030).

`scripts/seed_dev_learner.py` is what every frontend surface and every inspection
endpoint gets eyeballed against, and it had no test. That is how #022 came to
find `--reset` truncating the relational tables but not the AGE graph — leaving
stale nodes contradicting the relational data beside them on every reseed — and
how, at #030, only one of the three reset copies was clearing `learner_profile`.

The failure mode this guards is specific and nasty: when the seeded data is
wrong, a developer looking at a wrong screen cannot tell whether the screen is
broken or the data is. So the assertions are the docstring's *contract* section,
one test per promise, so a failure names which promise broke.

**Properties, not fixture contents.** These check "three consecutive days then a
gap", not that `_SESSIONS` holds twelve particular rows. Reshaping the seed data
should not be a test change — that is why the docstring lists properties.

Cross-table count consistency is deliberately absent: `error_counts` holds counts
up to 14 against 5 `error_observations` rows *by design* (fabricated end state,
not replayed history). See the seeder's "Incidental" docstring section before
adding an assertion here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from eval.agent.personas.schema import ALLOWED_ERROR_PATTERNS
from hable_ya.config import settings
from hable_ya.learner import graph as learner_graph
from hable_ya.learner.profile import is_calibrated_async
from scripts.learner_reset import (
    PROFILE_BASE_STATE,
    PROFILE_NOT_RESET,
    reset_learner_state,
)
from scripts.seed_dev_learner import seed

#: Pinned so the recency-relative properties are assertable at all. A Wednesday,
#: mid-month, mid-year: no month/year boundary inside the 20-day span the seed
#: covers, so a date-arithmetic bug cannot hide behind a rollover.
ANCHOR = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)

MODES = {"open", "role_play", "interview", "debate"}


@pytest.fixture
async def seeded(clean_learner_state: asyncpg.Pool) -> asyncpg.Pool:
    """A freshly-seeded learner, anchored at `ANCHOR`.

    `clean_learner_state` commits rather than rolling back, which these tests
    need: AGE does side-effecting DDL that does not reliably roll back
    (`tests/conftest.py`), and the graph assertions below depend on it.
    """
    async with clean_learner_state.acquire() as conn:
        await seed(conn, now=ANCHOR)
    return clean_learner_state


async def test_streak_is_three_consecutive_days_then_a_gap(
    seeded: asyncpg.Pool,
) -> None:
    """The property a streak calculation that ignores gaps gets wrong."""
    async with seeded.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT (started_at AT TIME ZONE 'UTC')::date AS d "
            "FROM sessions ORDER BY d DESC"
        )
    days = [row["d"] for row in rows]
    anchor = ANCHOR.date()

    assert days[0] == anchor, f"most recent session is {days[0]}, not the anchor"
    # Three consecutive days ending on the anchor...
    assert [(anchor - d).days for d in days[:3]] == [0, 1, 2], (
        f"expected a 3-day run ending {anchor}, got {days[:3]}"
    )
    # ...and then a break, or the streak is longer than advertised and a
    # gap-ignoring calculation would pass by accident.
    assert (anchor - days[3]).days > 3, (
        f"expected a gap after the 3-day run, but {days[3]} continues it"
    )


async def test_exactly_one_session_is_still_open(seeded: asyncpg.Pool) -> None:
    """The in-progress / crashed case the UI has to render."""
    async with seeded.acquire() as conn:
        open_sessions = await conn.fetchval(
            "SELECT count(*) FROM sessions WHERE ended_at IS NULL"
        )
    assert open_sessions == 1


async def test_modes_cover_null_and_all_four(seeded: asyncpg.Pool) -> None:
    """Pre-#023 rows (`mode IS NULL`) alongside every mode #023 added."""
    async with seeded.acquire() as conn:
        null_modes = await conn.fetchval(
            "SELECT count(*) FROM sessions WHERE mode IS NULL"
        )
        present = {
            row["mode"]
            for row in await conn.fetch(
                "SELECT DISTINCT mode FROM sessions WHERE mode IS NOT NULL"
            )
        }
    assert null_modes >= 1, "no pre-#023 NULL-mode session"
    assert present == MODES, f"modes {MODES - present} missing from the seed"


async def test_error_categories_straddle_the_curated_enum(
    seeded: asyncpg.Pool,
) -> None:
    """`errors[].type` has no enum, so the UI must survive both sides of it."""
    async with seeded.acquire() as conn:
        categories = {
            row["category"]
            for row in await conn.fetch("SELECT category FROM error_counts")
        }
    assert categories & ALLOWED_ERROR_PATTERNS, "no curated category seeded"
    assert categories - ALLOWED_ERROR_PATTERNS, (
        "every seeded category is in ALLOWED_ERROR_PATTERNS — the off-enum case "
        "the seed exists to exercise is gone"
    )


async def test_turns_exceed_the_profile_window(seeded: asyncpg.Pool) -> None:
    """Enough turns that the trailing-window aggregates are actually windowed."""
    async with seeded.acquire() as conn:
        turns = await conn.fetchval("SELECT count(*) FROM turns")
    assert turns > settings.profile_window_turns, (
        f"{turns} turns does not exceed the {settings.profile_window_turns}-turn "
        "window, so l1_reliance / speech_fluency are computed over everything"
    )


async def test_display_name_is_set_and_non_ascii(seeded: asyncpg.Pool) -> None:
    """The avatar initial is taken from the first code point (spec #021)."""
    async with seeded.acquire() as conn:
        name = await conn.fetchval(
            "SELECT display_name FROM learner_profile WHERE id = 1"
        )
    assert name, "display_name empty — the greeting shows its empty state"
    assert not name[0].isascii(), (
        f"{name!r} starts with ASCII; the accent case is untested"
    )


async def test_profile_is_calibrated_at_b1(seeded: asyncpg.Pool) -> None:
    """A placement row is what flips `is_calibrated`; the promotion sets B1."""
    async with seeded.acquire() as conn:
        band = await conn.fetchval("SELECT band FROM learner_profile WHERE id = 1")
        calibrated = await is_calibrated_async(conn)
    assert band == "B1"
    assert calibrated, "no placement row, so the cold-start diagnostic would re-run"


async def test_graph_mirrors_the_relational_aggregates(seeded: asyncpg.Pool) -> None:
    """#022's regression: the graph and the tables must agree on *what* exists.

    Compares key *sets*, not counts. Counts are the weaker check twice over: the
    node counters increment per call so magnitudes differ by design, and — the
    reason this test was rewritten during #030 — an uncleared graph reseeded with
    unchanged data has the same node count, because the writers `MERGE` on the
    key. Equal counts with different keys is exactly the stale-node state #022
    found, so the keys are what get asserted.
    """
    async with seeded.acquire() as conn:
        relational_vocab = {
            row["lemma"]
            for row in await conn.fetch("SELECT lemma FROM vocabulary_items")
        }
        relational_errors = {
            row["category"]
            for row in await conn.fetch("SELECT category FROM error_counts")
        }
        graph_vocab = await _graph_keys(conn, "VocabItem", "lemma")
        graph_errors = await _graph_keys(conn, "ErrorPattern", "category")

    assert relational_vocab and relational_errors, "nothing seeded to mirror"
    assert graph_vocab == relational_vocab, (
        "graph VocabItem lemmas do not match vocabulary_items: "
        f"only in graph {sorted(graph_vocab - relational_vocab)}, "
        f"only in table {sorted(relational_vocab - graph_vocab)}"
    )
    assert graph_errors == relational_errors, (
        "graph ErrorPattern categories do not match error_counts: "
        f"only in graph {sorted(graph_errors - relational_errors)}, "
        f"only in table {sorted(relational_errors - graph_errors)}"
    )


async def test_reset_clears_the_graph(clean_learner_state: asyncpg.Pool) -> None:
    """`TRUNCATE` does not touch AGE — the reset has to clear it explicitly.

    #022's actual bug, tested directly rather than inferred from a reseed. It
    needs its own test because the mirror above cannot see it on unchanged seed
    data: the writers `MERGE`, so re-seeding over stale nodes reproduces the same
    keys. Only a node the next seed will *not* write proves the graph was cleared.
    """
    async with clean_learner_state.acquire() as conn:
        await learner_graph.upsert_vocab(conn, lemma="palabra-obsoleta", at=ANCHOR)
        assert "palabra-obsoleta" in await _graph_keys(conn, "VocabItem", "lemma")

        await reset_learner_state(conn)

        assert await _graph_total_nodes(conn) == 0, (
            "nodes survived the reset — TRUNCATE does not clear AGE, so a reseed "
            "would leave stale graph state contradicting the relational data "
            "beside it (spec #022)"
        )


async def test_reseed_is_idempotent(seeded: asyncpg.Pool) -> None:
    """What `--reset` exists to promise: reseeding lands on the same state.

    Reset *and* seed, because `seed` alone is not idempotent — the turn and
    band-history inserts have no conflict handling, which is what makes the
    graph clear inside the reset load-bearing here.
    """
    async with seeded.acquire() as conn:
        before = await _state_snapshot(conn)
        await reset_learner_state(conn)
        await seed(conn, now=ANCHOR)
        after = await _state_snapshot(conn)
    assert before == after, f"reseed diverged: {before} -> {after}"


async def test_reset_covers_every_profile_column(
    clean_learner_state: asyncpg.Pool,
) -> None:
    """A new `learner_profile` column must be classified, not silently skipped.

    This is the guard that makes one shared definition sufficient rather than
    merely tidy. #026 proposes adding `turns_observed`; when it lands, this fails
    until someone decides whether a reset should clear it — instead of the seeder
    quietly carrying a stale value, which is exactly how #022's bug survived.
    """
    async with clean_learner_state.acquire() as conn:
        columns = {
            row["column_name"]
            for row in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'learner_profile'"
            )
        }
    unclassified = columns - set(PROFILE_BASE_STATE) - set(PROFILE_NOT_RESET)
    assert not unclassified, (
        f"learner_profile column(s) {sorted(unclassified)} are neither reset nor "
        "excluded. Add them to PROFILE_BASE_STATE (with a base value) or to "
        "PROFILE_NOT_RESET (with a reason) in scripts/learner_reset.py."
    )
    # And the reverse: a dropped column must not linger in the reset, where it
    # would make every reset fail on an unknown column.
    assert not set(PROFILE_BASE_STATE) - columns, (
        "PROFILE_BASE_STATE names a dead column"
    )


async def _graph_keys(conn: asyncpg.Connection, label: str, prop: str) -> set[str]:
    """The set of key values on every node of `label`.

    Uses `graph._fetch_cypher` rather than a raw query so the agtype decoding is
    the module's own: values arrive as `str` keeping their JSON quoting, so a
    lemma comes back as `'"viajar"'` and needs `json.loads`, not `str()`.
    """
    rows = await learner_graph._fetch_cypher(
        conn, f"MATCH (n:{label}) RETURN n.{prop}", "key"
    )
    return {str(row["key"]) for row in rows}


async def _graph_total_nodes(conn: asyncpg.Connection) -> int:
    rows = await learner_graph._fetch_cypher(conn, "MATCH (n) RETURN count(n)", "n")
    return int(rows[0]["n"]) if rows else 0


async def _state_snapshot(conn: asyncpg.Connection) -> dict[str, object]:
    """Row counts plus the profile row — enough to catch accumulation."""
    counts = {
        table: await conn.fetchval(f"SELECT count(*) FROM {table}")
        for table in (
            "sessions",
            "turns",
            "error_counts",
            "vocabulary_items",
            "band_history",
        )
    }
    profile = await conn.fetchrow(
        "SELECT band, sessions_completed, stable_sessions_at_band, display_name "
        "FROM learner_profile WHERE id = 1"
    )
    return {
        **counts,
        "profile": dict(profile) if profile else None,
        # Keys, not counts — see test_graph_mirrors_the_relational_aggregates.
        "graph_vocab": sorted(await _graph_keys(conn, "VocabItem", "lemma")),
        "graph_errors": sorted(await _graph_keys(conn, "ErrorPattern", "category")),
    }
