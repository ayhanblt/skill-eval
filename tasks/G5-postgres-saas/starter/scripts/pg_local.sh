#!/usr/bin/env bash
set -euo pipefail

PGDATA="${PGDATA:-/tmp/pg_skilleval}"
PGPORT="${PGPORT:-5433}"
export PG_DSN="dbname=saas_eval user=postgres host=/tmp port=${PGPORT}"

cmd="${1:-help}"
case "$cmd" in
  up)
    if [ ! -f "${PGDATA}/PG_VERSION" ]; then
      rm -rf "${PGDATA}"
      initdb -D "${PGDATA}" -U postgres --auth=trust >/dev/null
    fi
    if ! pg_ctl -D "${PGDATA}" status >/dev/null 2>&1; then
      pg_ctl -D "${PGDATA}" -o "-k /tmp -p ${PGPORT} -h ''" -l "${PGDATA}/postgres.log" start >/dev/null
    fi
    createdb -h /tmp -p "${PGPORT}" -U postgres saas_eval 2>/dev/null || true
    echo "PostgreSQL ready on /tmp:${PGPORT} (db=saas_eval)"
    ;;
  seed)
    psql -h /tmp -p "${PGPORT}" -U postgres -d saas_eval -v ON_ERROR_STOP=1 -f sql/migrations/001_initial_schema.sql
    python3 scripts/seed.py
    if [ -s sql/migrations/002_optimizations.sql ]; then
      psql -h /tmp -p "${PGPORT}" -U postgres -d saas_eval -v ON_ERROR_STOP=1 -f sql/migrations/002_optimizations.sql
      psql -h /tmp -p "${PGPORT}" -U postgres -d saas_eval -c "VACUUM ANALYZE;"
    fi
    ;;
  test)
    pytest -v
    ;;
  down)
    if pg_ctl -D "${PGDATA}" status >/dev/null 2>&1; then
      pg_ctl -D "${PGDATA}" stop >/dev/null
    fi
    ;;
  *)
    echo "Usage: $0 {up|seed|test|down}"
    exit 1
    ;;
esac
