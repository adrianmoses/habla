#!/usr/bin/env bash
# Restore a hable-ya Postgres + Apache AGE database from a custom-format dump
# produced by scripts/backup_db.sh.
#
# The dump is self-contained: it recreates the `age` extension, the AGE graph
# registration (ag_graph / ag_label), the label tables, and all relational +
# graph rows. No manual `CREATE EXTENSION age` pre-step is needed.
#
# Contract: restore into an EMPTY database (e.g. the one the Postgres image
# auto-creates from POSTGRES_DB on a fresh pgdata volume). Restoring over a
# populated database is NOT supported here — bring up a fresh volume first, or
# create a new target DB. --no-owner lets the dump load under whatever role owns
# the target (prod POSTGRES_USER may differ from the dev `hable_ya`); the runtime
# sets the AGE search_path per-connection, so the role-level search_path the
# original migration pinned is not required for serving.
#
# Usage:
#   scripts/restore_db.sh <dump-file>
#
# Env (defaults match the local dev stack):
#   POSTGRES_USER   DB role   (default: hable_ya)
#   POSTGRES_DB     DB name   (default: hable_ya)
#   DB_SERVICE      compose   (default: db)
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <dump-file>" >&2
  exit 2
fi

DUMP="$1"
if [[ ! -f "$DUMP" ]]; then
  echo "Dump file not found: ${DUMP}" >&2
  exit 2
fi

DB_USER="${POSTGRES_USER:-hable_ya}"
DB_NAME="${POSTGRES_DB:-hable_ya}"
DB_SERVICE="${DB_SERVICE:-db}"

echo "Restoring ${DUMP} → '${DB_NAME}' (role ${DB_USER})" >&2
echo "Target must be an EMPTY database (fresh pgdata volume)." >&2

# --no-owner: load objects as the connecting role regardless of dump ownership.
# --exit-on-error: fail loudly rather than leave a half-restored DB.
docker compose exec -T "$DB_SERVICE" \
  pg_restore --no-owner --exit-on-error -U "$DB_USER" -d "$DB_NAME" < "$DUMP"

echo "Restore complete. Verifying AGE graph registration…" >&2
docker compose exec -T "$DB_SERVICE" \
  psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT name FROM ag_catalog.ag_graph;" >&2
