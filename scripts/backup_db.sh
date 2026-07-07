#!/usr/bin/env bash
# Back up the hable-ya Postgres + Apache AGE database to a compressed custom-format
# dump. A plain pg_dump captures everything needed for a full restore, INCLUDING
# the AGE graph: pg_dump emits `CREATE EXTENSION age`, and AGE marks its catalog
# tables (ag_graph / ag_label) with pg_extension_config_dump so the graph
# registration + label tables + vertex/edge rows all travel in the dump. Verified
# by a dump→restore round-trip of the learner_knowledge graph (spec #017 spike).
#
# Usage:
#   scripts/backup_db.sh [output-file]
#
# Env (defaults match the local dev stack):
#   POSTGRES_USER   DB role      (default: hable_ya)
#   POSTGRES_DB     DB name      (default: hable_ya)
#   DB_SERVICE      compose svc  (default: db)
#   BACKUP_DIR      output dir   (default: ./backups) — used when no arg given
#
# Runs pg_dump INSIDE the db container via `docker compose exec`, so it works
# whether the stack was started from the base file or the prod overlay (the db is
# not host-published in prod).
set -euo pipefail

DB_USER="${POSTGRES_USER:-hable_ya}"
DB_NAME="${POSTGRES_DB:-hable_ya}"
DB_SERVICE="${DB_SERVICE:-db}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

if [[ $# -ge 1 ]]; then
  OUT="$1"
else
  mkdir -p "$BACKUP_DIR"
  OUT="${BACKUP_DIR}/habla-${DB_NAME}-$(date -u +%Y%m%dT%H%M%SZ).dump"
fi

echo "Backing up '${DB_NAME}' (role ${DB_USER}) → ${OUT}" >&2
# -Fc: custom format (compressed, selective pg_restore). -T over stdin so the
# dump streams to the host file.
docker compose exec -T "$DB_SERVICE" \
  pg_dump -Fc -U "$DB_USER" "$DB_NAME" > "$OUT"

BYTES=$(wc -c < "$OUT")
echo "Wrote ${OUT} (${BYTES} bytes)" >&2
