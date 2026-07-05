"""band_history

Revision ID: 99507a1b3027
Revises: bd55d203ae25
Create Date: 2026-04-26 00:00:00.000000+00:00

Spec 049 — adds the per-turn ``turns.cefr_band``, the audit log
``band_history``, and two ``learner_profile`` columns
(``stable_sessions_at_band``, ``last_band_change_at``) used by the
auto-leveling hysteresis.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "99507a1b3027"
down_revision: str | Sequence[str] | None = "bd55d203ae25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Same scoping convention as bd55d203ae25 — the role's search_path is
    # pinned to ag_catalog, so plain CREATE TABLE without this would route
    # into ag_catalog. Application state belongs in public.
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute(
        """
        ALTER TABLE turns
            ADD COLUMN cefr_band TEXT
                CHECK (cefr_band IS NULL
                       OR cefr_band IN ('A1','A2','B1','B2','C1'));
        """
    )
    op.execute(
        """
        ALTER TABLE learner_profile
            ADD COLUMN stable_sessions_at_band INT NOT NULL DEFAULT 0,
            ADD COLUMN last_band_change_at     TIMESTAMPTZ;
        """
    )
    op.execute(
        """
        CREATE TABLE band_history (
            id            BIGSERIAL PRIMARY KEY,
            from_band     TEXT CHECK (
                from_band IS NULL
                OR from_band IN ('A1','A2','B1','B2','C1')
            ),
            to_band       TEXT NOT NULL CHECK (
                to_band IN ('A1','A2','B1','B2','C1')
            ),
            reason        TEXT NOT NULL CHECK (
                reason IN ('placement','auto_promote','auto_demote','manual')
            ),
            signals       JSONB NOT NULL DEFAULT '{}'::jsonb,
            changed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX band_history_changed_at_idx "
        "ON band_history(changed_at DESC);"
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute("DROP TABLE IF EXISTS band_history;")
    op.execute(
        "ALTER TABLE learner_profile "
        "DROP COLUMN IF EXISTS last_band_change_at, "
        "DROP COLUMN IF EXISTS stable_sessions_at_band;"
    )
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS cefr_band;")
