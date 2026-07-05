"""enable_extensions

Revision ID: 20c019e280a9
Revises:
Create Date: 2026-04-21 21:48:23.848750+00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "20c019e280a9"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS age;")
    # Persist the AGE search_path at the role level so `RESET ALL` (asyncpg
    # runs this on every pool release) falls back to a path that still
    # resolves `ag_catalog` unqualified. Without this, the init-callback
    # `SET search_path` only survives until the first release-to-pool.
    op.execute('ALTER ROLE hable_ya SET search_path = ag_catalog, "$user", public;')


def downgrade() -> None:
    op.execute("ALTER ROLE hable_ya RESET search_path;")
    op.execute("DROP EXTENSION IF EXISTS age;")
