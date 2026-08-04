"""The learner's display name (spec #021) — validation and the single writer.

Deliberately narrow. The name is *UI-only*: it is read out of the raw
``learner_profile`` row by ``read.py`` and rendered by the SPA, and it is never
put on ``LearnerProfileSnapshot``. That matters structurally — the snapshot
feeds ``snapshot_to_profile()`` → ``render.py``'s ``## Learner`` block, so a
field on it is one careless edit away from the tutor's system prompt. Keeping
the name off that path means it has no route into the prompt at all, which is
why the cold-start byte-identity tests need no re-baselining.

Nor does it reach the AGE graph: ``graph.py`` interpolates identifiers into
dollar-quoted cypher behind ``_IDENT_RE``, and learner-supplied free text is
exactly the value that filter exists to fear. The name stays relational.

Normalization is a pure function so the rules are testable without a DB, the
same split #024 used for its observer state machine.
"""

from __future__ import annotations

import unicodedata

import asyncpg

#: Code points, counted after trimming. A layout bound, not a security one —
#: 40 characters fit Home's 96px serif greeting without wrapping past two
#: lines at the SPA's ``maxWidth: 520``.
MAX_DISPLAY_NAME = 40

#: Unicode general categories that never belong in a name: C0/C1 controls
#: (``Cc``) and invisible formatting characters such as RTL overrides and the
#: zero-width joiner (``Cf``).
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf"})


class InvalidDisplayName(ValueError):
    """The submitted name violates the length or character rules."""


def normalize_display_name(raw: str | None) -> str | None:
    """Trim a submitted name, or raise if it cannot be stored.

    ``None`` and anything that trims to empty mean *clear it* — "not set" has
    to stay representable, so both map to SQL ``NULL`` rather than to ``''``.

    There is no character allowlist: accented Latin, non-Latin scripts and
    internal spaces must all work. The value is parameterized into SQL by
    asyncpg, never interpolated into cypher, and escaped by React on render, so
    a regex here would defend nothing it does not already have.
    """
    if raw is None:
        return None

    trimmed = raw.strip()
    if not trimmed:
        return None

    # Code points, not UTF-16 units or bytes: 'Ángela' is six characters and a
    # name outside the BMP should not cost double.
    if len(trimmed) > MAX_DISPLAY_NAME:
        raise InvalidDisplayName(
            f"display_name must be at most {MAX_DISPLAY_NAME} characters"
        )

    if any(unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in trimmed):
        raise InvalidDisplayName(
            "display_name must not contain control or formatting characters"
        )

    return trimmed


async def set_display_name(pool: asyncpg.Pool, value: str | None) -> None:
    """Persist an already-normalized name onto the singleton profile row.

    Takes the *output* of ``normalize_display_name``, so the caller cannot
    write a value that skipped validation.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE learner_profile
               SET display_name = $1,
                   updated_at = now()
             WHERE id = 1
            """,
            value,
        )
