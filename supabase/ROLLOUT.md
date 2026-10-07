# Rolling out migration 03 and the backend hardening

Nothing here has been applied to a live project. This is the order to do it in, with the scripts that
back each step. Every step before "Apply" is read-only.

## 0. Decide first: is Supabase also the backend's database?
The backend creates its own `public.events` table (`SQLAlchemy create_all`, no `workspace_id`). Migration
01 creates a different `public.events` (`workspace_id NOT NULL`). Same name, different tables. If the
backend's `DATABASE_URL` points at the Supabase database they collide, and 03's policies (which need
`workspace_id`) cannot work on the backend's table.
- Backend on its own Postgres (the `docker-compose.yml` default): no collision. Apply 03 to the Supabase
  project only if you use it.
- Backend on the Supabase database: do not apply 03 until you have chosen which table owns the name
  (e.g. move the backend to its own schema). `00_preflight.sql` reports this as a `FAIL`.

## 1. Preflight (read-only)
```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/rollout/00_preflight.sql
```
Resolve every `FAIL`. Read every `warn`: it lists current exposure (RLS off, anon grants), row counts, and the
reminder that `events` becomes append-only, so any job or edge function that UPDATEs/DELETEs it must change
first (archiving goes through `archive_events()`, service role only).

## 2. Back up, then rehearse on a branch/staging database
Take a backup (Supabase: Database > Backups, or `pg_dump`). Apply there first and run the behavioural tests,
which create their own scratch database and never touch real data:
```bash
PGHOST=... PGUSER=... PGPASSWORD=... supabase/tests/run.sh
```

## 3. Apply (one transaction)
```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f supabase/migrations/03_security_hardening.sql
```
(`01` was edited so it no longer creates policies that fail on a fresh database; a database where 01 already
ran is unaffected, because 03 drops and recreates every policy it touches.)

## 4. Verify (read-only) and spot-check by role
```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/rollout/03_verify.sql
```
Then, with real keys, from outside: the anon key must get a permission error on `events`; a member key sees
only its workspace; a non-member key sees nothing; the service role still works.

## 5. Roll back (only the operational parts)
`supabase/rollout/03_rollback.sql` removes the append-only triggers and `archive_events()`. It does not reopen
RLS, the anon grant or the `add_workspace_user()` hole; for the full pre-03 state restore the step 2 backup.

## Backend deploy (separate from the SQL)
1. Set `PHANTOM_PLATFORM_TENANT_ID` to your operator workspace id if you want cross-tenant admins. Existing
   `admin` keys are now admin of their own workspace only. List who holds them:
   `SELECT k.name, w.name AS workspace FROM api_keys k JOIN workspaces w ON w.id = k.tenant_id JOIN roles r ON r.id = k.role_id WHERE r.name = 'admin';`
   (backend database), then decide which belong in the platform workspace and re-mint those there.
2. Deploy. The image now includes `websockets`; WebSocket clients must send an API key as the first message
   (the bundled frontend has a key field).
3. Rebuild snapshots, twice; the second run must print `snapshots rebuilt: 0`:
   ```bash
   python -m app.scripts.rebuild_snapshots
   python -m app.scripts.rebuild_snapshots
   ```
   Spot-check an entity with `replaycheck` (`replaycheck/examples/phantomos_adapter.py`).
4. Money: clients must send amounts as decimal strings (or integers); floats are rejected on money events.
   State and portfolio amounts are now decimal strings (`schema_version: 2`).
5. Workspace creation now needs the bootstrap key or a platform admin key.
