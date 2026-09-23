#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'EOF'
Usage: entrypoint.sh <command> [args...]

Commands:
  text-ingest          Ingest JSONL into Postgres
  text-ingest-daily    Run text ingest workflow using env-configured inputs
  data-ui              Start Vue + FastAPI web UI
  shell                Open bash shell
  help                 Show this help

Examples:
  entrypoint.sh text-ingest --input /app/runtime/exports/library.jsonl
  entrypoint.sh text-ingest-daily
  entrypoint.sh data-ui
EOF
}

require_dsn() {
  if [[ -z "${POSTGRES_DSN:-}" ]]; then
    echo "ERROR: POSTGRES_DSN is required for this command." >&2
    exit 2
  fi
}

as_bool() {
  local v
  v=$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')
  [[ "$v" == "1" || "$v" == "true" || "$v" == "yes" || "$v" == "y" || "$v" == "on" ]]
}

cmd=${1:-help}
shift || true

# Apply pending DB migrations. Runs on every start and is a no-op once the
# database is at the image's schema version; the applied set lives in the
# database's schema_version table, so nothing is remembered in the filesystem.
# Failure refuses to start by default (DB_INIT_FAIL_HARD=1) -- see
# textIngest/migrations/README.md. A missing DSN is not a failure: the setup
# wizard stores it on first run and the next start migrates.
if [[ -x "/app/textIngest/run_migrations.sh" ]]; then
  /app/textIngest/run_migrations.sh
fi

case "$cmd" in
  -h|--help|help)
    show_help
    ;;
  text-ingest)
    require_dsn
    exec python /app/textIngest/ingest_jsonl_to_postgres.py \
      --dsn "$POSTGRES_DSN" \
      "$@"
    ;;
  text-ingest-daily)
    exec /app/textIngest/run_daily_text_ingest.sh "$@"
    ;;
  data-ui)
    echo "[startup] nofile soft=$(ulimit -Sn 2>/dev/null || true) hard=$(ulimit -Hn 2>/dev/null || true)"
    if [[ -d "/proc/self/fd" ]]; then
      echo "[startup] open_fds=$(ls -1 /proc/self/fd 2>/dev/null | wc -l | tr -d ' ')"
    fi
    exec uvicorn webapi.main:app --host 0.0.0.0 --port "${DATA_UI_PORT:-8501}"
    ;;
  shell)
    exec /bin/bash "$@"
    ;;
  *)
    echo "ERROR: unknown command: $cmd" >&2
    show_help >&2
    exit 2
    ;;
esac
