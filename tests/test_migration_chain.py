"""Every migration's `downgrade()`, run in both directions (spec #031).

Before this, exactly one of five had ever executed: #021 added the suite's first
round-trip and it covers `-1`, so `f1e6a742b90c` was the only revision whose
reverse path had ever run. The other four were untested code on the deploy path,
documented as supported by their own existence.

**Nothing was broken.** Running the chain by hand while writing the spec, on a
scratch database, `upgrade head → downgrade base → upgrade head` succeeded and
rebuilt everything — including the statement the roadmap suspected,
`20c019e280a9`'s `DROP EXTENSION IF EXISTS age;` without `CASCADE`. It cannot
fail the way that was predicted: alembic enforces chain order, so that downgrade
only ever runs when going to `base`, which necessarily drops the graph first. Even
a *foreign* AGE graph does not block it, because AGE registers graph schemas as
members of the extension rather than dependents.

So this is a regression guard, not a repair. Five reverse paths work; nothing kept
them working, and the next schema change was free to break any of them silently
with an incident as the discovery moment.

What it asserts beyond "the downgrade ran": that the forward path can **rebuild**
from whatever the downgrade left behind. That is the property that would actually
bite, and residue is demonstrably real here — `DROP EXTENSION age` leaves the
`ag_catalog` schema in place, and the re-upgrade works only because
`CREATE EXTENSION IF NOT EXISTS age` copes with finding it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

#: In chain order, base → head, each with the object it introduces. The probe is
#: what makes a downgrade observable: asserting "the downgrade ran without error"
#: would pass for a `downgrade()` whose body was deleted entirely.
CHAIN: tuple[tuple[str, str], ...] = (
    ("20c019e280a9", "extension:age"),
    ("bd55d203ae25", "table:learner_profile"),
    ("99507a1b3027", "table:band_history"),
    ("c7f3a9b21d84", "column:sessions.mode"),
    ("f1e6a742b90c", "column:learner_profile.display_name"),
    ("6a7b8c9d0e1f", "table:external_session_handoffs"),
)

LEARNER_TABLES = (
    "learner_profile",
    "sessions",
    "turns",
    "error_observations",
    "error_counts",
    "vocabulary_items",
    "band_history",
    "external_session_handoffs",
)


def _config() -> Config:
    return Config(str(_ALEMBIC_INI))


async def _run(fn: object, *args: str) -> None:
    # Alembic's env.py calls `asyncio.run` internally, so it cannot run on a
    # thread that already owns a loop — same reason `upgrade_to_head` does this.
    await asyncio.to_thread(fn, _config(), *args)  # type: ignore[arg-type]


async def _exists(conn: asyncpg.Connection, probe: str) -> bool:
    """Resolve one `CHAIN` probe against the live catalog.

    Catalog queries rather than `SELECT 1 FROM <table>`: the point is whether the
    migration's object is *there*, which must stay answerable when the table is
    absent rather than raising.
    """
    kind, _, target = probe.partition(":")
    if kind == "extension":
        return bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = $1)",
                target,
            )
        )
    if kind == "table":
        return bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1)",
                target,
            )
        )
    if kind == "column":
        table, _, column = target.partition(".")
        return bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = $1 "
                "AND column_name = $2)",
                table,
                column,
            )
        )
    raise AssertionError(f"unknown probe kind: {probe}")


async def _graph_exists(conn: asyncpg.Connection) -> bool:
    """Whether the `learner_knowledge` graph is registered.

    Guarded on the extension: once `age` is dropped, `ag_catalog.ag_graph` is gone
    too and querying it would raise rather than answer False.
    """
    if not await _exists(conn, "extension:age"):
        return False
    return bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM ag_catalog.ag_graph "
            "WHERE name = 'learner_knowledge')"
        )
    )


async def _public_tables(conn: asyncpg.Connection) -> set[str]:
    return {
        row["table_name"]
        for row in await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    }


async def _schema_exists(conn: asyncpg.Connection, name: str) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.schemata "
            "WHERE schema_name = $1)",
            name,
        )
    )


@pytest.fixture
async def conn(migration_db: str):  # type: ignore[no-untyped-def]
    """A plain connection to the throwaway database.

    Not `db_pool`: that pool runs `LOAD 'age'` per connection
    (`hable_ya/db/connection.py`), which fails once the extension is dropped —
    and dropping it is the point here.
    """
    connection = await asyncpg.connect(dsn=migration_db)
    try:
        yield connection
    finally:
        await connection.close()


async def test_full_chain_round_trip(conn: asyncpg.Connection) -> None:
    """`head → base → head`, asserting the state at every stop.

    The final upgrade is the assertion that matters. "Did `downgrade()` run
    without error" is the uninteresting half; "did it leave something the forward
    path can rebuild from" is what an operator would discover during an incident.
    """
    await _run(command.upgrade, "head")
    assert await _public_tables(conn) >= set(LEARNER_TABLES)
    assert await _exists(conn, "extension:age")
    assert await _graph_exists(conn)

    await _run(command.downgrade, "base")

    remaining = await _public_tables(conn)
    assert remaining == {"alembic_version"}, (
        f"downgrade base left {sorted(remaining - {'alembic_version'})} in public; "
        "alembic_version is alembic's own bookkeeping and is expected to survive"
    )
    assert not await _exists(conn, "extension:age"), "the age extension survived"
    assert not await _graph_exists(conn)

    # `ag_catalog` outlives its extension, and the re-upgrade below depends on
    # that being harmless: 20c019e280a9 runs `CREATE EXTENSION IF NOT EXISTS age`,
    # which has to cope with finding the schema already there. Asserted rather
    # than assumed, because it is the one piece of downgrade residue this chain
    # actually leaves.
    assert await _schema_exists(conn, "ag_catalog"), (
        "ag_catalog no longer survives DROP EXTENSION — the residue this chain "
        "leaves has changed, so re-check that the re-upgrade below still holds "
        "for the reason documented here"
    )

    await _run(command.upgrade, "head")
    assert await _public_tables(conn) >= set(LEARNER_TABLES), (
        "the forward path could not rebuild from what downgrade base left behind"
    )
    assert await _exists(conn, "extension:age")
    assert await _graph_exists(conn)


async def test_each_revision_round_trips(conn: asyncpg.Connection) -> None:
    """Every `downgrade()` individually: present → gone at -1 → present again.

    One test walking the chain rather than five parametrized ones, because each
    step is a separate alembic invocation and they dominate the runtime. Every
    assertion names its revision, so a failure still identifies which
    `downgrade()` broke.
    """
    await _run(command.downgrade, "base")

    for revision, probe in CHAIN:
        await _run(command.upgrade, revision)
        assert await _exists(conn, probe), f"{revision}: upgrade did not create {probe}"

        await _run(command.downgrade, "-1")
        assert not await _exists(conn, probe), (
            f"{revision}: downgrade left {probe} behind"
        )

        # Back up, both to prove the reverse path is rebuildable at this step and
        # to position the chain for the next revision.
        await _run(command.upgrade, revision)
        assert await _exists(conn, probe), (
            f"{revision}: re-upgrade after downgrade did not restore {probe}"
        )

    await _run(command.upgrade, "head")


async def test_running_a_migration_does_not_silence_the_app_loggers(
    conn: asyncpg.Connection,
) -> None:
    """Alembic's `fileConfig` must not disable the loggers already in memory.

    Not a migration property — a *hosting* property, and a real defect until
    #033 tripped over it. `api/main.py`'s lifespan calls `upgrade_to_head()`
    after the routers are imported, so `env.py` runs inside the live process
    with every module logger already created. `fileConfig` defaults to
    `disable_existing_loggers=True`, which set `disabled = True` on all of them
    for the rest of the process: a server that finished booting logged nothing
    from its own request paths, silently and permanently.

    Asserted here because this file is the only place that drives alembic
    end-to-end, and the failure is invisible to every test that does not read
    log output.
    """
    logger = logging.getLogger("hable_ya.api.session")
    assert logger.disabled is False, "precondition: the logger starts enabled"

    await _run(command.upgrade, "head")

    assert logger.disabled is False, (
        "an alembic run disabled an application logger — check "
        "`disable_existing_loggers=False` in hable_ya/db/alembic/env.py"
    )
