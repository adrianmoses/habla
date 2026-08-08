"""Every SQL snippet in README.md actually runs (spec #022).

`README.md:154` documented a `turns` query that could not execute — it selected
`created_at` (the column is `timestamp`) and `l1_reliance_score` (no such
column; that signal is computed in `aggregations.py` and never stored per-turn).
Two errors in five columns, in the first query an operator would try, surviving
long enough to be found by a spec about something else.

Inspection is what let it rot, so this executes them instead. The cypher
snippets are covered too: they live inside ```sql fences (they are SQL calls
wrapping cypher bodies), and each block runs on one connection with its
statements in order — which is what makes the block's own
`SET search_path = ag_catalog, …` do its job for the statements after it.
"""

from __future__ import annotations

import re
from pathlib import Path

import asyncpg
import pytest

README = Path(__file__).resolve().parents[1] / "README.md"

#: Blocks are executed statement-by-statement in order, on one connection.
_SQL_BLOCK = re.compile(r"^```sql\n(.*?)^```", re.S | re.M)


def _blocks() -> list[str]:
    return _SQL_BLOCK.findall(README.read_text())


def _statements(block: str) -> list[str]:
    """Split a block into statements.

    Splitting on `;` is sufficient rather than principled: no dollar-quoted
    cypher body in the README contains a semicolon. If one ever does, this
    splits mid-body and the test fails loudly — which is the right failure, but
    the fix is to quote-track here, not to delete the snippet.
    """
    without_comments = re.sub(r"--[^\n]*", "", block)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def test_readme_has_sql_blocks_to_check() -> None:
    # Guards against the regex silently matching nothing after a docs reshuffle,
    # which would turn every test below into a vacuous pass.
    blocks = _blocks()
    assert len(blocks) >= 2, f"expected the inspection sections, found {len(blocks)}"
    assert any("FROM turns" in b for b in blocks)
    assert any("cypher(" in b for b in blocks)


@pytest.mark.parametrize("index", range(len(_blocks())))
async def test_readme_sql_block_executes(
    clean_learner_state: asyncpg.Pool, index: int
) -> None:
    block = _blocks()[index]
    async with clean_learner_state.acquire() as conn:
        for statement in _statements(block):
            try:
                await conn.execute(statement)
            except asyncpg.PostgresError as exc:
                one_line = " ".join(statement.split())
                pytest.fail(
                    f"README.md block {index + 1} has a statement that does not "
                    f"run:\n  {one_line}\n  {type(exc).__name__}: {exc}"
                )


async def test_readme_turns_query_selects_real_columns(
    clean_learner_state: asyncpg.Pool,
) -> None:
    """Pinned regression for the specific defect #022 found.

    The block test above would catch it, but this names it — so a future reader
    seeing this test knows `created_at` / `l1_reliance_score` were real, and
    does not reintroduce them from an old draft.
    """
    turns_stmt = next(
        s
        for block in _blocks()
        for s in _statements(block)
        if "FROM turns" in s and "SELECT" in s.upper()
    )
    assert "created_at" not in turns_stmt
    assert "l1_reliance_score" not in turns_stmt

    async with clean_learner_state.acquire() as conn:
        await conn.execute(turns_stmt)
