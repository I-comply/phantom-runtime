-- Read-only. Run AFTER migration 03 (as postgres / service role). Raises on the first failed check:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/rollout/03_verify.sql
-- Static checks of the catalog. The behavioural checks (anon denied, tenant isolation, append-only,
-- escalation closed) are in supabase/tests/test_security.sql; run those on a scratch/branch database
-- (supabase/tests/run.sh), never against production data.
\set ON_ERROR_STOP on

DO $$
DECLARE t text;
BEGIN
  -- RLS on, never disabled
  FOR t IN SELECT unnest(ARRAY['events','events_archive','workspaces','workspace_users','api_keys']) LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname='public' AND c.relname=t AND c.relrowsecurity) THEN
      RAISE EXCEPTION 'FAIL: RLS is off on public.%', t;
    END IF;
  END LOOP;

  -- anon has no privileges on any of them; authenticated has no write privileges beyond INSERT on events
  IF EXISTS (SELECT 1 FROM information_schema.role_table_grants
             WHERE grantee='anon' AND table_schema='public'
               AND table_name IN ('events','events_archive','workspaces','workspace_users','api_keys')) THEN
    RAISE EXCEPTION 'FAIL: anon still has table privileges';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.role_table_grants
             WHERE grantee='authenticated' AND table_schema='public'
               AND table_name IN ('events','events_archive','workspaces','workspace_users','api_keys')
               AND privilege_type IN ('UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER')) THEN
    RAISE EXCEPTION 'FAIL: authenticated has UPDATE/DELETE/TRUNCATE on a protected table';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.role_table_grants
             WHERE grantee='authenticated' AND table_schema='public' AND table_name IN ('events_archive','api_keys')) THEN
    RAISE EXCEPTION 'FAIL: authenticated can access events_archive/api_keys';
  END IF;

  -- policies: the helper-based ones exist, the recursive one is gone
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='events' AND cmd='SELECT') THEN
    RAISE EXCEPTION 'FAIL: no SELECT policy on events';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='workspace_users'
             AND qual LIKE '%FROM workspace_users%') THEN
    RAISE EXCEPTION 'FAIL: workspace_users policy still queries workspace_users (infinite recursion)';
  END IF;

  -- append-only triggers
  IF (SELECT count(*) FROM pg_trigger WHERE tgrelid='public.events'::regclass AND NOT tgisinternal
      AND tgname IN ('events_no_update_delete','events_no_truncate')) <> 2 THEN
    RAISE EXCEPTION 'FAIL: append-only triggers missing on public.events';
  END IF;

  -- SECURITY DEFINER functions pin their search_path and are not executable by anon/PUBLIC
  FOR t IN SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='public' AND p.prosecdef
             AND (p.proconfig IS NULL OR NOT EXISTS (SELECT 1 FROM unnest(p.proconfig) c WHERE c LIKE 'search_path=%')) LOOP
    RAISE EXCEPTION 'FAIL: SECURITY DEFINER function without a pinned search_path: %', t;
  END LOOP;
  IF has_function_privilege('anon', 'public.add_workspace_user(uuid,varchar,varchar)', 'EXECUTE')
     OR has_function_privilege('anon', 'public.archive_events(timestamptz)', 'EXECUTE') THEN
    RAISE EXCEPTION 'FAIL: anon can execute add_workspace_user/archive_events';
  END IF;
  IF has_function_privilege('authenticated', 'public.archive_events(timestamptz)', 'EXECUTE') THEN
    RAISE EXCEPTION 'FAIL: authenticated can execute archive_events';
  END IF;

  -- the escalation fix is in the function body
  IF pg_get_functiondef('public.add_workspace_user(uuid,varchar,varchar)'::regprocedure) NOT LIKE '%only a workspace owner or admin%' THEN
    RAISE EXCEPTION 'FAIL: add_workspace_user() does not check the caller''s role';
  END IF;
END $$;

SELECT 'migration 03 catalog checks: all passed' AS result;
