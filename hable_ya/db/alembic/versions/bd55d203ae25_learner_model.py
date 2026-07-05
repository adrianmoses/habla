"""learner_model

Revision ID: bd55d203ae25
Revises: 20c019e280a9
Create Date: 2026-04-22 21:22:48.319957+00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "bd55d203ae25"
down_revision: str | Sequence[str] | None = "20c019e280a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Spec 028 pins the role's search_path to `ag_catalog, "$user", public` so
    # AGE functions resolve unqualified. That also routes plain `CREATE TABLE`
    # into `ag_catalog`, which we do NOT want — these tables are application
    # state and belong in `public`. Scope the switch to this transaction.
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute(
        """
        CREATE TABLE learner_profile (
            id                 SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            band               TEXT NOT NULL CHECK (band IN ('A1','A2','B1','B2','C1')),
            sessions_completed INT  NOT NULL DEFAULT 0,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE sessions (
            session_id    TEXT PRIMARY KEY,
            started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at      TIMESTAMPTZ,
            theme_domain  TEXT,
            band_at_start TEXT NOT NULL CHECK (band_at_start IN ('A1','A2','B1','B2','C1'))
        );
        """
    )
    op.execute(
        """
        CREATE TABLE turns (
            id                BIGSERIAL PRIMARY KEY,
            session_id        TEXT        NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            timestamp         TIMESTAMPTZ NOT NULL,
            learner_utterance TEXT        NOT NULL,
            fluency_signal    TEXT        NOT NULL CHECK (fluency_signal IN ('weak','moderate','strong')),
            L1_used           BOOLEAN     NOT NULL,
            raw_extra         JSONB       NOT NULL DEFAULT '{}'::jsonb
        );
        """
    )
    op.execute("CREATE INDEX turns_session_idx ON turns(session_id);")
    op.execute("CREATE INDEX turns_timestamp_idx ON turns(timestamp DESC);")

    op.execute(
        """
        CREATE TABLE error_observations (
            id            BIGSERIAL PRIMARY KEY,
            turn_id       BIGINT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
            category      TEXT   NOT NULL,
            produced_form TEXT   NOT NULL,
            target_form   TEXT   NOT NULL
        );
        """
    )
    op.execute(
        "CREATE INDEX error_observations_category_idx ON error_observations(category);"
    )

    op.execute(
        """
        CREATE TABLE error_counts (
            category     TEXT PRIMARY KEY,
            count        INT NOT NULL DEFAULT 0,
            last_seen_at TIMESTAMPTZ NOT NULL
        );
        """
    )

    op.execute(
        """
        CREATE TABLE vocabulary_items (
            lemma            TEXT PRIMARY KEY,
            sample_form      TEXT NOT NULL,
            production_count INT  NOT NULL DEFAULT 0,
            first_seen_at    TIMESTAMPTZ NOT NULL,
            last_seen_at     TIMESTAMPTZ NOT NULL
        );
        """
    )
    op.execute(
        "CREATE INDEX vocabulary_items_last_seen_idx ON vocabulary_items(last_seen_at DESC);"
    )

    op.execute("INSERT INTO learner_profile (id, band) VALUES (1, 'A2');")

    # AGE's create_graph raises if the graph already exists (Stage 0 spike);
    # guard via ag_catalog.ag_graph so the migration is safe to re-run.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'learner_knowledge'
            ) THEN
                PERFORM create_graph('learner_knowledge');
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path TO public, ag_catalog;")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'learner_knowledge'
            ) THEN
                PERFORM drop_graph('learner_knowledge'::name, true);
            END IF;
        END $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS vocabulary_items;")
    op.execute("DROP TABLE IF EXISTS error_counts;")
    op.execute("DROP TABLE IF EXISTS error_observations;")
    op.execute("DROP TABLE IF EXISTS turns;")
    op.execute("DROP TABLE IF EXISTS sessions;")
    op.execute("DROP TABLE IF EXISTS learner_profile;")
