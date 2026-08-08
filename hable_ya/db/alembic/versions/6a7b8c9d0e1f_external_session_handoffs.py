"""External session handoffs for La Libreta.

Revision ID: 6a7b8c9d0e1f
Revises: f1e6a742b90c
Create Date: 2026-08-08 00:00:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6a7b8c9d0e1f"
down_revision: str | Sequence[str] | None = "f1e6a742b90c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute(
        """
        CREATE TABLE external_session_handoffs (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL CHECK (source = 'la-libreta'),
            source_ref TEXT NOT NULL,
            source_date DATE NOT NULL,
            mode TEXT NOT NULL CHECK (mode = 'speaking'),
            prompt_text TEXT NOT NULL,
            structures JSONB NOT NULL
                CHECK (jsonb_typeof(structures) = 'array'),
            target TEXT NOT NULL,
            callback_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            callback_attempts SMALLINT NOT NULL DEFAULT 0,
            callback_delivered_at TIMESTAMPTZ,
            UNIQUE (source, source_ref, source_date)
        );
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute("DROP TABLE IF EXISTS external_session_handoffs;")
