"""learner_display_name

Revision ID: f1e6a742b90c
Revises: c7f3a9b21d84
Create Date: 2026-08-04 00:00:00.000000+00:00

Spec 021 — the learner's own name, for the greeting and the avatar initial.
Nullable with no default and no backfill: the existing row's name is genuinely
unset, and NULL is how "not set" stays representable. The singleton
``CHECK (id = 1)`` is untouched — this spec gives the one learner a name, it
does not make room for a second.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1e6a742b90c"
down_revision: str | Sequence[str] | None = "c7f3a9b21d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Same scoping convention as the learner-model migrations — the role's
    # search_path is pinned to ag_catalog, so bare DDL would route there.
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute("ALTER TABLE learner_profile ADD COLUMN display_name TEXT;")


def downgrade() -> None:
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute("ALTER TABLE learner_profile DROP COLUMN IF EXISTS display_name;")
