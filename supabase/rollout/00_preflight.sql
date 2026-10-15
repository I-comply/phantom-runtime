-- Read-only. Run on the target database BEFORE migration 03:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/rollout/00_preflight.sql
-- Every FAIL line must be resolved first; WARN lines need a human decision. Changes nothing.
\set ON_ERROR_STOP on
\pset format unaligned
\pset tuples_only on

SELECT 'info: ' || version();

-- 1. Is public.events the Supabase event store (workspace_id) or the backend's own table (no workspace_id)?
--    Both are called "events". If Supabase is ALSO the backend's DATABASE_URL, migrations 01/02 and the
--    backend's create_all collide on this table. Decide which owns it before going further.
SELECT CASE
  WHEN to_regclass('public.events') IS NULL THEN 'ok: public.events does not exist yet (01 will create it)'
  WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='events' AND column_name='workspace_id')
    THEN 'ok: public.events has workspace_id (Supabase event store shape)'
  ELSE 'FAIL: public.events exists WITHOUT workspace_id (the backend''s table). Migration 03 policies need workspace_id; do not apply 03 to this database'
END;

-- 2. Prerequisites 03 relies on
SELECT CASE WHEN to_regclass('public.workspace_users') IS NULL THEN 'FAIL: public.workspace_users missing (run 02 first)' ELSE 'ok: public.workspace_users exists' END;
SELECT CASE WHEN to_regprocedure('auth.uid()') IS NULL THEN 'FAIL: auth.uid() missing (not a Supabase database?)' ELSE 'ok: auth.uid() exists' END;
SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN 'ok: role service_role exists' ELSE 'FAIL: role service_role missing' END;

-- 3. Current exposure (what 03 closes)
SELECT 'warn: RLS is OFF on public.' || relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind='r' AND NOT c.relrowsecurity AND relname IN ('events','events_archive','workspaces','workspace_users','api_keys');
SELECT 'warn: anon has ' || privilege_type || ' on public.' || table_name FROM information_schema.role_table_grants
 WHERE grantee='anon' AND table_schema='public' AND table_name IN ('events','events_archive','workspaces','workspace_users','api_keys');
SELECT 'warn: authenticated has ' || string_agg(privilege_type, ',') || ' on public.' || table_name FROM information_schema.role_table_grants
 WHERE grantee='authenticated' AND table_schema='public' AND table_name IN ('events','events_archive','workspaces','workspace_users','api_keys') GROUP BY table_name;

-- 4. Existing data 03 will touch
SELECT 'info: rows in public.events = ' || (SELECT count(*) FROM public.events) WHERE to_regclass('public.events') IS NOT NULL;
SELECT 'info: rows in public.events_archive = ' || (SELECT count(*) FROM public.events_archive) WHERE to_regclass('public.events_archive') IS NOT NULL;
SELECT 'warn: ' || count(*) || ' workspace_users rows with role owner/admin (re-check who may add members after 03)'
  FROM public.workspace_users WHERE role IN ('owner','admin') AND to_regclass('public.workspace_users') IS NOT NULL;

-- 5. Things 03 replaces: existing policies and triggers on events (will be dropped and recreated)
SELECT 'info: policy on ' || tablename || ': ' || policyname FROM pg_policies WHERE schemaname='public' AND tablename IN ('events','workspaces','workspace_users');
SELECT 'warn: existing trigger on public.events: ' || tgname FROM pg_trigger WHERE tgrelid = to_regclass('public.events') AND NOT tgisinternal;
-- Anything that UPDATEs or DELETEs events (jobs, edge functions, admin scripts) will start failing after 03:
SELECT 'warn: 03 makes public.events append-only; check that no job UPDATEs/DELETEs it (use archive_events() instead)';
