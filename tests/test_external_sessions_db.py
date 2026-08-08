"""Handoff persistence against a real Postgres (spec #033).

These are the properties a fake pool cannot demonstrate, because the database
is the thing enforcing them: the three-part unique key, what happens when two
requests race for it, and the conditional UPDATEs that make completion and
callback delivery safe to repeat.

Uses `db_pool` rather than the transaction-per-test `db_conn`, because the
concurrency test needs two connections that can see each other's committed
work — which is exactly what a shared transaction would hide. Each test cleans
up the rows it wrote.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import date

import asyncpg
import pytest
import pytest_asyncio

from hable_ya.handoff import repo

TODAY = date(2026, 5, 2)


@pytest_asyncio.fixture
async def handoffs(db_pool: asyncpg.Pool) -> asyncpg.Pool:
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM external_session_handoffs")
    yield db_pool
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM external_session_handoffs")


async def _create(
    conn: asyncpg.Connection, handoff_id: str, **overrides: object
) -> tuple[object, bool]:
    payload: dict[str, object] = {
        "source": "la-libreta",
        "source_ref": "p02",
        "source_date": TODAY,
        "mode": "speaking",
        "text": "Describe una decisión.",
        "structures": ["condicional compuesto"],
        "target": "monólogo de 3 minutos",
        "callback_url": None,
    }
    payload.update(overrides)
    return await repo.insert_or_get(conn, handoff_id=handoff_id, **payload)  # type: ignore[arg-type]


async def test_insert_then_replay_returns_the_first_row(
    handoffs: asyncpg.Pool,
) -> None:
    async with handoffs.acquire() as conn:
        first, created = await _create(conn, "sess_first")
        second, created_again = await _create(
            conn, "sess_second", text="Una consigna distinta"
        )

    assert created is True
    assert created_again is False
    assert second.id == first.id == "sess_first"  # type: ignore[attr-defined]
    assert second.created_at == first.created_at  # type: ignore[attr-defined]
    # First payload wins: the replay's different text did not overwrite it.
    assert second.text == "Describe una decisión."  # type: ignore[attr-defined]


async def test_a_different_date_is_a_different_handoff(
    handoffs: asyncpg.Pool,
) -> None:
    async with handoffs.acquire() as conn:
        first, _ = await _create(conn, "sess_may2")
        second, created = await _create(
            conn, "sess_may3", source_date=date(2026, 5, 3)
        )

    assert created is True
    assert second.id != first.id  # type: ignore[attr-defined]


async def test_structures_round_trip_through_jsonb(handoffs: asyncpg.Pool) -> None:
    structures = ["condicional compuesto", "pluscuamperfecto de subjuntivo"]
    async with handoffs.acquire() as conn:
        created, _ = await _create(conn, "sess_json", structures=structures)
        reread = await repo.get(conn, "sess_json")

    assert created.structures == structures  # type: ignore[attr-defined]
    assert reread is not None and reread.structures == structures


async def test_concurrent_creates_produce_one_row(handoffs: asyncpg.Pool) -> None:
    """Simultaneous requests for the same daily prompt → one handoff.

    The failure this rules out is *two rows*, which would hand La Libreta two
    different deep links for one prompt and split the learner's practice across
    them.

    Two details are what make it a real race rather than a race-shaped test.
    The connections are acquired and established **before** the gather: with
    `pool.acquire()` inside each task, the losers block on connection setup and
    the "concurrent" creates quietly serialize — verified by injecting a
    check-then-act insert, which this test passed until the acquire moved out.
    And a barrier releases them together, so all of them observe the same empty
    table before any of them writes.
    """
    racers = 4  # the pool's max size

    async with AsyncExitStack() as stack:
        conns = [
            await stack.enter_async_context(handoffs.acquire())
            for _ in range(racers)
        ]
        barrier = asyncio.Barrier(racers)

        async def create(index: int, conn: asyncpg.Connection) -> tuple[object, bool]:
            await barrier.wait()
            return await _create(conn, f"sess_race_{index}")

        results = await asyncio.gather(
            *(create(i, conn) for i, conn in enumerate(conns)),
            return_exceptions=True,
        )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert not failures, f"the race raised instead of resolving: {failures}"
    ids = {handoff.id for handoff, _ in results}  # type: ignore[misc]
    created_flags = [created for _, created in results]  # type: ignore[misc]
    assert len(ids) == 1, f"the race produced {len(ids)} handoffs: {ids}"
    assert created_flags.count(True) == 1, "more than one caller believed it created"

    async with handoffs.acquire() as conn:
        rows = await conn.fetchval(
            "SELECT count(*) FROM external_session_handoffs "
            "WHERE source_ref = 'p02' AND source_date = $1",
            TODAY,
        )
    assert rows == 1


async def test_started_at_records_the_first_start_only(
    handoffs: asyncpg.Pool,
) -> None:
    async with handoffs.acquire() as conn:
        await _create(conn, "sess_start")
        await repo.mark_started(conn, "sess_start")
        first = await repo.get(conn, "sess_start")
        await repo.mark_started(conn, "sess_start")
        second = await repo.get(conn, "sess_start")

    assert first is not None and first.started_at is not None
    assert second is not None and second.started_at == first.started_at


async def test_completion_transitions_exactly_once(handoffs: asyncpg.Pool) -> None:
    async with handoffs.acquire() as conn:
        await _create(conn, "sess_done")
        first, transitioned = await repo.mark_completed(conn, "sess_done")
        second, again = await repo.mark_completed(conn, "sess_done")

    assert transitioned is True
    assert again is False, "a repeat completion would fire a second callback"
    assert first is not None and second is not None
    assert second.completed_at == first.completed_at


async def test_concurrent_completions_transition_once(
    handoffs: asyncpg.Pool,
) -> None:
    # The double-click / reconnect case, run for real: only one caller may be
    # told it transitioned, because that is what gates callback delivery.
    async with handoffs.acquire() as conn:
        await _create(conn, "sess_double")

    async def complete() -> bool:
        async with handoffs.acquire() as conn:
            _, transitioned = await repo.mark_completed(conn, "sess_double")
            return transitioned

    outcomes = await asyncio.gather(*(complete() for _ in range(5)))
    assert outcomes.count(True) == 1


async def test_completing_an_unknown_id_reports_nothing(
    handoffs: asyncpg.Pool,
) -> None:
    async with handoffs.acquire() as conn:
        handoff, transitioned = await repo.mark_completed(conn, "sess_nope")
    assert handoff is None
    assert transitioned is False


async def test_a_delivered_callback_is_terminal(handoffs: asyncpg.Pool) -> None:
    async with handoffs.acquire() as conn:
        await _create(conn, "sess_cb", callback_url="https://example.com/cb")
        await repo.mark_completed(conn, "sess_cb")

        recorded = await repo.record_callback_attempt(
            conn, "sess_cb", attempts=1, delivered=True, error=None
        )
        delivered = await repo.get(conn, "sess_cb")

        # A late second run cannot overwrite the delivery or add attempts.
        again = await repo.record_callback_attempt(
            conn, "sess_cb", attempts=2, delivered=False, error="http 500"
        )
        after = await repo.get(conn, "sess_cb")

    assert recorded is True
    assert again is False
    assert delivered is not None and delivered.callback_delivered_at is not None
    assert after is not None
    assert after.callback_delivered_at == delivered.callback_delivered_at
    assert after.callback_attempts == 1


async def test_a_failed_callback_records_attempts_and_stays_retriable(
    handoffs: asyncpg.Pool,
) -> None:
    async with handoffs.acquire() as conn:
        await _create(conn, "sess_fail", callback_url="https://example.com/cb")
        await repo.mark_completed(conn, "sess_fail")
        await repo.record_callback_attempt(
            conn, "sess_fail", attempts=2, delivered=False, error="http 503"
        )
        failed = await repo.get(conn, "sess_fail")
        error = await conn.fetchval(
            "SELECT callback_last_error FROM external_session_handoffs WHERE id = $1",
            "sess_fail",
        )

    assert failed is not None
    assert failed.callback_attempts == 2
    assert failed.callback_delivered_at is None
    assert error == "http 503"


async def test_the_source_and_mode_checks_are_enforced_by_the_database(
    handoffs: asyncpg.Pool,
) -> None:
    # Defence in depth behind the pydantic enums: the row itself refuses a
    # source or mode the spec does not accept.
    async with handoffs.acquire() as conn:
        with pytest.raises(asyncpg.PostgresError):
            await _create(conn, "sess_bad_source", source="someone-else")
        with pytest.raises(asyncpg.PostgresError):
            await _create(conn, "sess_bad_mode", mode="listening")
