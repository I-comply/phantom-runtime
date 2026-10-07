#!/usr/bin/env bash
# Applies the Supabase stub + migrations to a scratch database and runs the security tests.
# Needs a reachable PostgreSQL (PGHOST/PGPORT/PGUSER/PGPASSWORD) with permission to CREATE DATABASE.
set -euo pipefail
cd "$(dirname "$0")/.."
DB="phantom_supabase_test_$$"
psql -q -v ON_ERROR_STOP=1 -d "${PGDATABASE:-postgres}" -c "CREATE DATABASE $DB"
trap 'psql -q -d "${PGDATABASE:-postgres}" -c "DROP DATABASE IF EXISTS $DB" >/dev/null' EXIT
for f in tests/00_supabase_stub.sql migrations/*.sql tests/test_security.sql; do
  echo "== $f"
  psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$f"
done
