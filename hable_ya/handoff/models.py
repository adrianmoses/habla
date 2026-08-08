"""The durable handoff row as a typed value object (spec #033)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

#: Every column the read paths need. Kept as one constant because three call
#: sites (the learner read endpoint, the WebSocket resolver, the completion
#: action) must agree on the shape `handoff_from_row` is given.
HANDOFF_COLUMNS = (
    "id, source, source_ref, source_date, mode, prompt_text, structures, "
    "target, callback_url, created_at, started_at, completed_at, "
    "callback_attempts, callback_delivered_at"
)


@dataclass(slots=True, frozen=True)
class SpeakingHandoff:
    """One `external_session_handoffs` row.

    `text`, `structures` and `target` are La Libreta's, stored and rendered
    verbatim — Habla never parses `target` into a timer and never rewrites the
    prompt. Everything else is Habla's own lifecycle state.
    """

    id: str
    source: str
    source_ref: str
    date: date
    mode: str
    text: str
    structures: list[str]
    target: str
    created_at: datetime
    callback_url: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    callback_attempts: int = 0
    callback_delivered_at: datetime | None = None


def _structures(raw: Any) -> list[str]:
    """Normalize the `structures` JSONB column to a list of strings.

    asyncpg hands back `str` for a jsonb column unless a codec is registered,
    and a list once one is — both shapes appear across the pool and the plain
    connections the tests use, so decode defensively rather than assuming.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


def handoff_from_row(row: Any) -> SpeakingHandoff:
    return SpeakingHandoff(
        id=row["id"],
        source=row["source"],
        source_ref=row["source_ref"],
        date=row["source_date"],
        mode=row["mode"],
        text=row["prompt_text"],
        structures=_structures(row["structures"]),
        target=row["target"],
        callback_url=row["callback_url"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        callback_attempts=row["callback_attempts"],
        callback_delivered_at=row["callback_delivered_at"],
    )
