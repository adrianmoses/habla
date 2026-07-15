"""sessions.mode

Revision ID: c7f3a9b21d84
Revises: 99507a1b3027
Create Date: 2026-07-15 00:00:00.000000+00:00

Spec 023 — per-session conversation mode (open / debate / role_play /
interview). Nullable so pre-023 rows stay valid; the CHECK mirrors the
enum-column convention used for the band columns.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7f3a9b21d84"
down_revision: str | Sequence[str] | None = "99507a1b3027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Same scoping convention as the learner-model migrations — the role's
    # search_path is pinned to ag_catalog, so bare DDL would route there.
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute(
        """
        ALTER TABLE sessions
            ADD COLUMN mode TEXT
                CHECK (mode IS NULL
                       OR mode IN ('open', 'debate', 'role_play', 'interview'));
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS mode;")
