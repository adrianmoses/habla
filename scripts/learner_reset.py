"""The one definition of "reset the learner state" (spec #030).

Three copies of this used to exist — `tests/conftest.py`'s `clean_learner_state`,
`seed_dev_learner.py`'s `--reset`, and `benchmark_graph_writes.py`'s `_reset` —
and two of them carried a comment claiming they ran "the same statement" as the
fixture. Neither did. #022 found the first consequence: the scripts truncated the
relational tables but not the AGE graph (`TRUNCATE` does not touch AGE), so every
reseed left stale graph nodes contradicting the relational data beside them.

The second consequence was still live when #030 was written. Only the fixture
reset `learner_profile`; the seeder got away with it because `_seed_bands`
happens to overwrite exactly the five mutable columns the fixture clears. One new
column (#026 proposes `turns_observed`) and the same bug returns in a new place.
Hence `PROFILE_BASE_STATE` below, and the test that asserts it still covers the
table.

**Dev and test only.** It lives in `scripts/` rather than `hable_ya/` on purpose:
hatchling packages `hable_ya`, `api` and `analiza`, so a function that deletes
every learner row is structurally unimportable from a deployed runtime rather
than merely warned about in a docstring.
"""

from __future__ import annotations

from typing import Any, Final

import asyncpg

from hable_ya.learner import graph as learner_graph

#: Truncated together — `CASCADE` would pull most of these in anyway via
#: `turns.session_id` / `error_observations.turn_id`, but naming them keeps the
#: set reviewable. `learner_profile` is absent deliberately: it is a schema-
#: enforced singleton (`CHECK (id = 1)`), so it is updated in place below rather
#: than truncated and re-inserted.
LEARNER_TABLES: Final[tuple[str, ...]] = (
    "error_observations",
    "error_counts",
    "vocabulary_items",
    "turns",
    "sessions",
    "band_history",
)

#: The state migration `bd55d203ae25` leaves `learner_profile` in, enumerated
#: rather than derived from column defaults: `band` has no DEFAULT, its base
#: value comes from that migration's seed `INSERT INTO learner_profile (id, band)
#: VALUES (1, 'A2')`. Enumeration is what makes the base state knowable;
#: `test_reset_covers_every_profile_column` is what keeps it complete.
PROFILE_BASE_STATE: Final[dict[str, Any]] = {
    "band": "A2",
    "sessions_completed": 0,
    "stable_sessions_at_band": 0,
    "last_band_change_at": None,
    "display_name": None,
}

#: Columns a reset must *not* touch, with the reason it would be wrong to.
PROFILE_NOT_RESET: Final[dict[str, str]] = {
    "id": "the singleton primary key — CHECK (id = 1)",
    "created_at": "when the row was created; resetting state is not a new profile",
    "updated_at": "maintained by the write path, not by callers",
}


def truncate_sql() -> str:
    """`TRUNCATE` for every learner table, built from `LEARNER_TABLES`."""
    return f"TRUNCATE {', '.join(LEARNER_TABLES)} RESTART IDENTITY CASCADE"


def _profile_update_sql() -> str:
    assignments = ", ".join(
        f"{column} = ${i}" for i, column in enumerate(PROFILE_BASE_STATE, start=1)
    )
    return f"UPDATE learner_profile SET {assignments} WHERE id = 1"


async def clear_graph(conn: asyncpg.Connection) -> None:
    """Delete every node and edge in the AGE graph.

    Separate from `reset_learner_state` only so a caller can be explicit about
    wanting the graph alone. `TRUNCATE` cannot do this — AGE stores the graph in
    its own schema, which is the whole substance of the #022 bug.
    """
    await conn.execute(
        f"SELECT * FROM cypher('{learner_graph.GRAPH}', $$ "
        f"MATCH (n) DETACH DELETE n $$) AS (v ag_catalog.agtype)"
    )


async def reset_learner_state(conn: asyncpg.Connection) -> None:
    """Return the learner to a freshly-migrated state: tables, graph, profile.

    All three, in that order. Any caller that needs one of them almost certainly
    needs all three — that assumption is what the three previous copies got
    wrong in two different ways.
    """
    await conn.execute(truncate_sql())
    await clear_graph(conn)
    await conn.execute(_profile_update_sql(), *PROFILE_BASE_STATE.values())
