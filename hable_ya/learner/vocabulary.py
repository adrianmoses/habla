"""VocabularyRepo — lemmatize learner utterances + upsert per-lemma counts.

Lemmatization is delegated to
:func:`eval.scoring.recast.content_lemma_surfaces`, which shares its POS
filter with the recast scorer so runtime and eval see the same content-word
universe. spaCy runs off-thread (``asyncio.to_thread``) so the single
transaction wrapping this call doesn't hold the event loop during
lemmatization. First call pays a ~2s model-load cost; subsequent calls
are ~1ms.

Methods accept an ``asyncpg.Connection`` so writes compose into the shared
ingestion transaction alongside `turns`, errors, and AGE graph writes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import asyncpg

from eval.scoring.recast import content_lemma_surfaces

logger = logging.getLogger(__name__)


class VocabularyRepo:
    @staticmethod
    async def record(
        conn: asyncpg.Connection,
        *,
        utterance: str,
        at: datetime,
    ) -> list[str]:
        """Lemmatize, upsert each lemma, return the ordered list observed.

        If spaCy or the `es_core_news_sm` model are unavailable, logs and
        returns `[]` so the ingest path continues (consistent with the
        `ingest_failed`-style graceful-degradation posture).
        """
        try:
            pairs = await asyncio.to_thread(content_lemma_surfaces, utterance)
        except (OSError, ImportError) as exc:
            logger.warning(
                "spaCy lemmatization skipped (%s) — vocabulary not recorded",
                exc,
            )
            return []
        for lemma, sample in pairs:
            await conn.execute(
                """
                INSERT INTO vocabulary_items
                    (lemma, sample_form, production_count, first_seen_at, last_seen_at)
                VALUES ($1, $2, 1, $3, $3)
                ON CONFLICT (lemma) DO UPDATE
                SET production_count = vocabulary_items.production_count + 1,
                    last_seen_at = EXCLUDED.last_seen_at
                """,
                lemma,
                sample,
                at,
            )
        return [lemma for lemma, _sample in pairs]

    @staticmethod
    async def top_recent(conn: asyncpg.Connection, *, limit: int = 5) -> list[str]:
        rows = await conn.fetch(
            """
            SELECT lemma FROM vocabulary_items
            ORDER BY last_seen_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [r["lemma"] for r in rows]
