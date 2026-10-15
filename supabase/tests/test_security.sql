-- Run with: psql -v ON_ERROR_STOP=1 -f tests/test_security.sql   (after the stub and migrations 01-03).
-- Every check raises an exception on failure; a clean exit means all passed.
\set ON_ERROR_STOP on
SET client_min_messages = warning;
\o /dev/null

INSERT INTO auth.users(id, email) VALUES
  ('11111111-1111-1111-1111-111111111111', 'owner@x'),
  ('22222222-2222-2222-2222-222222222222', 'outsider@x'),
  ('33333333-3333-3333-3333-333333333333', 'member@x'),
  ('44444444-4444-4444-4444-444444444444', 'admin@x');
INSERT INTO public.workspaces(id, name, owner_id) VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'A', '11111111-1111-1111-1111-111111111111');
INSERT INTO public.workspace_users(workspace_id, user_id, role) VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'owner'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '33333333-3333-3333-3333-333333333333', 'member'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '44444444-4444-4444-4444-444444444444', 'admin');
INSERT INTO public.events(entity_id, event_type, payload, workspace_id) VALUES
  ('e1', 'init', '{"secret": 1}', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
  ('e2', 'init', '{"secret": 2}', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');

-- helper: run a statement as a role/user, expect the given SQLSTATE (or success when NULL)
CREATE OR REPLACE FUNCTION pg_temp.as_user(p_role TEXT, p_uid TEXT, p_sql TEXT, p_expect TEXT)
RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE v_state TEXT; v_out TEXT;
BEGIN
  PERFORM set_config('request.jwt.claim.sub', coalesce(p_uid, ''), true);
  EXECUTE format('SET LOCAL ROLE %I', p_role);
  BEGIN
    IF p_sql ~* '^\s*select' THEN EXECUTE p_sql INTO v_out; ELSE EXECUTE p_sql; END IF;
    v_state := NULL;
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_state = RETURNED_SQLSTATE;
  END;
  RESET ROLE;
  IF v_state IS DISTINCT FROM p_expect THEN
    RAISE EXCEPTION 'FAIL as % (%): % -> state %, expected %', p_role, p_uid, p_sql, v_state, p_expect;
  END IF;
  RETURN v_out;
END $$;
GRANT EXECUTE ON FUNCTION pg_temp.as_user(TEXT, TEXT, TEXT, TEXT) TO PUBLIC;

-- 1. RLS is on for every table (01 used to turn it off for events)
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relname IN ('events','events_archive','workspaces','workspace_users','api_keys')
               AND NOT c.relrowsecurity) THEN
    RAISE EXCEPTION 'FAIL: RLS disabled on a public table';
  END IF;
END $$;

-- 2. anon has no access at all
SELECT pg_temp.as_user('anon', NULL, 'SELECT count(*)::text FROM public.events', '42501');
SELECT pg_temp.as_user('anon', NULL, 'SELECT count(*)::text FROM public.workspace_users', '42501');
SELECT pg_temp.as_user('anon', NULL, 'SELECT count(*)::text FROM public.api_keys', '42501');

-- 3. tenant isolation on events
DO $$ BEGIN
  IF pg_temp.as_user('authenticated','11111111-1111-1111-1111-111111111111','SELECT count(*)::text FROM public.events',NULL) <> '2' THEN RAISE EXCEPTION 'FAIL: owner should see 2 events'; END IF;
  IF pg_temp.as_user('authenticated','33333333-3333-3333-3333-333333333333','SELECT count(*)::text FROM public.events',NULL) <> '2' THEN RAISE EXCEPTION 'FAIL: member should see 2 events'; END IF;
  IF pg_temp.as_user('authenticated','22222222-2222-2222-2222-222222222222','SELECT count(*)::text FROM public.events',NULL) <> '0' THEN RAISE EXCEPTION 'FAIL: outsider sees events'; END IF;
END $$;

-- 4. workspace_users no longer recurses, and only shows your own workspaces
DO $$ BEGIN
  IF pg_temp.as_user('authenticated','11111111-1111-1111-1111-111111111111','SELECT count(*)::text FROM public.workspace_users',NULL) <> '3' THEN RAISE EXCEPTION 'FAIL: owner should see 3 members'; END IF;
  IF pg_temp.as_user('authenticated','22222222-2222-2222-2222-222222222222','SELECT count(*)::text FROM public.workspace_users',NULL) <> '0' THEN RAISE EXCEPTION 'FAIL: outsider sees members'; END IF;
END $$;

-- 5. insert only into your own workspace
SELECT pg_temp.as_user('authenticated','33333333-3333-3333-3333-333333333333',
  $q$INSERT INTO public.events(entity_id,event_type,payload,workspace_id) VALUES ('e3','x','{}','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')$q$, NULL);
SELECT pg_temp.as_user('authenticated','22222222-2222-2222-2222-222222222222',
  $q$INSERT INTO public.events(entity_id,event_type,payload,workspace_id) VALUES ('e4','x','{}','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')$q$, '42501');

-- 6. append-only: authenticated has no UPDATE/DELETE privilege; even service_role and the table owner are blocked by trigger
SELECT pg_temp.as_user('authenticated','11111111-1111-1111-1111-111111111111',$q$UPDATE public.events SET event_type='y'$q$, '42501');
SELECT pg_temp.as_user('authenticated','11111111-1111-1111-1111-111111111111',$q$DELETE FROM public.events$q$, '42501');
SELECT pg_temp.as_user('service_role',NULL,$q$UPDATE public.events SET event_type='y'$q$, '23001');
SELECT pg_temp.as_user('service_role',NULL,$q$DELETE FROM public.events$q$, '23001');
SELECT pg_temp.as_user('service_role',NULL,$q$TRUNCATE public.events$q$, '23001');
DO $$ BEGIN
  BEGIN UPDATE public.events SET event_type = 'y'; RAISE EXCEPTION 'FAIL: owner UPDATE succeeded';
  EXCEPTION WHEN restrict_violation THEN NULL; END;
END $$;

-- 7. privilege escalation via add_workspace_user is closed
SELECT pg_temp.as_user('authenticated','22222222-2222-2222-2222-222222222222',
  $q$SELECT public.add_workspace_user('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','outsider@x','owner')::text$q$, '42501');
SELECT pg_temp.as_user('authenticated','33333333-3333-3333-3333-333333333333',
  $q$SELECT public.add_workspace_user('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','member@x','owner')::text$q$, '42501');
SELECT pg_temp.as_user('authenticated','44444444-4444-4444-4444-444444444444',
  $q$SELECT public.add_workspace_user('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','outsider@x','owner')::text$q$, '42501');
SELECT pg_temp.as_user('authenticated', NULL,
  $q$SELECT public.add_workspace_user('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','outsider@x','member')::text$q$, '42501');
SELECT pg_temp.as_user('anon', NULL,
  $q$SELECT public.add_workspace_user('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','outsider@x','member')::text$q$, '42501');
SELECT pg_temp.as_user('authenticated','44444444-4444-4444-4444-444444444444',
  $q$SELECT public.add_workspace_user('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','outsider@x','member')::text$q$, NULL);
DO $$ BEGIN
  IF pg_temp.as_user('authenticated','22222222-2222-2222-2222-222222222222','SELECT count(*)::text FROM public.events',NULL) <> '3' THEN
    RAISE EXCEPTION 'FAIL: admin-added member should now see events'; END IF;
END $$;
-- an admin cannot demote the owner
SELECT pg_temp.as_user('authenticated','44444444-4444-4444-4444-444444444444',
  $q$SELECT public.add_workspace_user('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','owner@x','viewer')::text$q$, NULL);
DO $$ BEGIN
  IF (SELECT role FROM public.workspace_users WHERE user_id = '11111111-1111-1111-1111-111111111111') <> 'owner' THEN
    RAISE EXCEPTION 'FAIL: admin demoted the owner'; END IF;
END $$;
-- the owner may grant owner
SELECT pg_temp.as_user('authenticated','11111111-1111-1111-1111-111111111111',
  $q$SELECT public.add_workspace_user('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','admin@x','owner')::text$q$, NULL);

-- 8. archive_events: service_role only, moves rows, nothing is lost
SELECT pg_temp.as_user('authenticated','11111111-1111-1111-1111-111111111111',$q$SELECT public.archive_events(now() + interval '1 day')::text$q$, '42501');
SELECT pg_temp.as_user('anon',NULL,$q$SELECT public.archive_events(now() + interval '1 day')::text$q$, '42501');
DO $$ DECLARE v_total BIGINT; v_moved TEXT;
BEGIN
  SELECT count(*) INTO v_total FROM public.events;
  v_moved := pg_temp.as_user('service_role', NULL, $q$SELECT public.archive_events(now() + interval '1 day')::text$q$, NULL);
  IF v_moved::bigint <> v_total THEN RAISE EXCEPTION 'FAIL: archived % of % events', v_moved, v_total; END IF;
  IF (SELECT count(*) FROM public.events) <> 0 OR (SELECT count(*) FROM public.events_archive) <> v_total THEN
    RAISE EXCEPTION 'FAIL: archive counts wrong'; END IF;
END $$;
-- the archiving flag is transaction-local: deletes are blocked again afterwards
SELECT pg_temp.as_user('service_role',NULL,$q$DELETE FROM public.events$q$, NULL);  -- no rows left, trigger is per-row: nothing to reject
INSERT INTO public.events(entity_id,event_type,payload,workspace_id) VALUES ('e9','x','{}','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');
SELECT pg_temp.as_user('service_role',NULL,$q$DELETE FROM public.events$q$, '23001');

\o
SELECT 'supabase security tests: all passed' AS result;
