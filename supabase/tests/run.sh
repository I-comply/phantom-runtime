#!/usr/bin/env bash
# Applies the Supabase stub + migrations to a scratch database and runs the security tests.
# Needs a reachable PostgreSQL (PGHOST/PGPORT/PGUSER/PGPASSWORD) with permission to CREATE DATABASE.
set -euo pipefail
cd "$(dirname "$0")/.."
DB="phantom_supabase_test_$$"
psql -q -v ON_ERROR_STOP=1 -d "${PGDATABASE:-postgres}" -c "CREATE DATABASE $DB"
trap 'psql -q -d "${PGDATABASE:-postgres}" -c "DROP DATABASE IF EXISTS $DB" >/dev/null' EXIT
for f in tests/00_supabase_stub.sql migrations/*.sql tests/test_security.sql rollout/03_verify.sql; do
  echo "== $f"
  psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$f"
done
# rollback script: applies cleanly, leaves RLS on, and brings back an UPDATE-able events table
echo "== rollout/03_rollback.sql"
psql -q -v ON_ERROR_STOP=1 -d "$DB" --single-transaction -f rollout/03_rollback.sql
psql -q -v ON_ERROR_STOP=1 -d "$DB" -c "DO \$\$ BEGIN
  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid='public.events'::regclass) THEN RAISE EXCEPTION 'rollback turned RLS off'; END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='public.events'::regclass AND tgname IN ('events_no_update_delete','events_no_truncate')) THEN RAISE EXCEPTION 'append-only trigger still present'; END IF;
END \$\$;"
