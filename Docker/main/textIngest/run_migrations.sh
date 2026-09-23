#!/usr/bin/env bash
set -euo pipefail

# Apply pending database migrations. Runs on EVERY container start.
#
# DB_INIT_FAIL_HARD now defaults to 1: running on a half-migrated database is
# worse than refusing to start, because the failure would surface far from its
# cause. Set it to 0 to restore the old best-effort behaviour.

as_bool() {
  local v
  v=$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')
  [[ "$v" == "1" || "$v" == "true" || "$v" == "yes" || "$v" == "y" || "$v" == "on" ]]
}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

DB_INIT_ON_START=${DB_INIT_ON_START:-1}
DB_INIT_FAIL_HARD=${DB_INIT_FAIL_HARD:-1}
DB_INIT_LOG=${DB_INIT_LOG:-/app/runtime/logs/db_init.log}
DB_INIT_MIGRATIONS_DIR=${DB_INIT_MIGRATIONS_DIR:-${SCRIPT_DIR}/migrations}
DB_INIT_CONNECT_TIMEOUT=${DB_INIT_CONNECT_TIMEOUT:-15}
DB_INIT_BACKUP=${DB_INIT_BACKUP:-1}
DB_INIT_BACKUP_DIR=${DB_INIT_BACKUP_DIR:-/app/runtime/backups}
DB_INIT_BACKUP_KEEP=${DB_INIT_BACKUP_KEEP:-3}
DB_INIT_REQUIRE_BACKUP=${DB_INIT_REQUIRE_BACKUP:-0}
DB_INIT_ALLOW_DOWNGRADE=${DB_INIT_ALLOW_DOWNGRADE:-0}
DB_INIT_APP_VERSION_FILE=${DB_INIT_APP_VERSION_FILE:-/app/webapi/static/version.json}
DB_INIT_DRY_RUN=${DB_INIT_DRY_RUN:-0}
DB_MIGRATIONS_PY=${DB_MIGRATIONS_PY:-${SCRIPT_DIR}/db_migrations.py}

if ! as_bool "$DB_INIT_ON_START"; then
  exit 0
fi

mkdir -p "$(dirname "$DB_INIT_LOG")"

if [[ ! -f "$DB_MIGRATIONS_PY" ]]; then
  echo "[$(date -Is)] ERROR db-init failed: runner missing: $DB_MIGRATIONS_PY" >>"$DB_INIT_LOG"
  if as_bool "$DB_INIT_FAIL_HARD"; then
    exit 1
  fi
  exit 0
fi

# No DSN yet is a legitimate state: the setup wizard writes it on first run and
# the next start migrates. Not an error.
if [[ -z "${POSTGRES_DSN:-}" ]]; then
  echo "[$(date -Is)] WARN db-init skipped: POSTGRES_DSN is empty" >>"$DB_INIT_LOG"
  exit 0
fi

args=(
  --dsn "$POSTGRES_DSN"
  --migrations-dir "$DB_INIT_MIGRATIONS_DIR"
  --log "$DB_INIT_LOG"
  --connect-timeout "$DB_INIT_CONNECT_TIMEOUT"
  --app-version-file "$DB_INIT_APP_VERSION_FILE"
)

if as_bool "$DB_INIT_BACKUP"; then
  args+=(--backup-dir "$DB_INIT_BACKUP_DIR" --backup-keep "$DB_INIT_BACKUP_KEEP")
else
  args+=(--no-backup)
fi
if as_bool "$DB_INIT_REQUIRE_BACKUP"; then
  args+=(--require-backup)
fi
if as_bool "$DB_INIT_ALLOW_DOWNGRADE"; then
  args+=(--allow-downgrade)
fi
if as_bool "$DB_INIT_DRY_RUN"; then
  args+=(--dry-run)
fi

set +e
python "$DB_MIGRATIONS_PY" "${args[@]}"
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
  exit 0
fi

if as_bool "$DB_INIT_FAIL_HARD"; then
  echo "[$(date -Is)] ERROR db-init failed (exit $rc); refusing to start (DB_INIT_FAIL_HARD=1)" >>"$DB_INIT_LOG"
  exit 1
fi

echo "[$(date -Is)] WARN db-init failed (exit $rc) but DB_INIT_FAIL_HARD=0; continuing" >>"$DB_INIT_LOG"
exit 0
