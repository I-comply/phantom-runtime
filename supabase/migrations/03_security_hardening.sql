-- 03_security_hardening.sql
-- Fixes found by reading and executing 01/02 on PostgreSQL 16:
--   * 01 disabled RLS on public.events and granted SELECT to anon (any holder of the public anon key
--     could read every workspace's events through PostgREST). Its policies also failed to create on a
--     fresh database (public.workspace_users did not exist yet).
--   * 02's workspace_users SELECT policy referenced its own table: "infinite recursion detected in
--     policy", so every workspace-scoped query failed for authenticated users.
--   * "Immutable event store" was enforced by grants only.
-- Idempotent. Safe to run on a database where 01/02 already ran, including one where RLS was disabled.

-- ============================================================
-- 1. Membership helper (SECURITY DEFINER avoids policy recursion)
-- ============================================================
CREATE OR REPLACE FUNCTION public.is_workspace_member(p_workspace_id UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.workspace_users
    WHERE workspace_id = p_workspace_id AND user_id = auth.uid()
  )
$$;
REVOKE ALL ON FUNCTION public.is_workspace_member(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_workspace_member(UUID) TO authenticated, service_role;

-- ============================================================
-- 2. Row level security: on, never disabled
-- ============================================================
ALTER TABLE public.events          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.events_archive  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspaces      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_keys        ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view workspace events" ON public.events;
DROP POLICY IF EXISTS "Users can insert events in their workspace" ON public.events;
CREATE POLICY "Users can view workspace events"
  ON public.events FOR SELECT TO authenticated
  USING (public.is_workspace_member(workspace_id));
CREATE POLICY "Users can insert events in their workspace"
  ON public.events FOR INSERT TO authenticated
  WITH CHECK (public.is_workspace_member(workspace_id) AND (created_by IS NULL OR created_by = auth.uid()));

DROP POLICY IF EXISTS "Users can view their workspaces" ON public.workspaces;
CREATE POLICY "Users can view their workspaces"
  ON public.workspaces FOR SELECT TO authenticated
  USING (public.is_workspace_member(id) OR owner_id = auth.uid());

DROP POLICY IF EXISTS "Users can view workspace members" ON public.workspace_users;
CREATE POLICY "Users can view workspace members"
  ON public.workspace_users FOR SELECT TO authenticated
  USING (public.is_workspace_member(workspace_id));

-- events_archive and api_keys have no policy on purpose: deny-all for anon/authenticated.
-- 02 granted INSERT on workspaces/workspace_users to authenticated without any INSERT policy, so those
-- inserts were already denied; workspace creation goes through create_workspace() (SECURITY DEFINER).

-- ============================================================
-- 3. Grants: least privilege. Supabase's default privileges give anon/authenticated ALL on new
--    public tables, so revoke first, then grant exactly what is used.
-- ============================================================
REVOKE ALL ON public.events, public.events_archive, public.workspaces, public.workspace_users, public.api_keys
  FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.events TO authenticated;
GRANT SELECT ON public.workspaces, public.workspace_users TO authenticated;
GRANT ALL ON public.events, public.events_archive, public.workspaces, public.workspace_users, public.api_keys
  TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.events_id_seq TO authenticated, service_role;

-- ============================================================
-- 4. Append-only: UPDATE, DELETE and TRUNCATE are rejected for every role except through
--    archive_events(), which moves old rows to events_archive first.
-- ============================================================
CREATE OR REPLACE FUNCTION public.events_append_only()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('phantom.archiving', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'public.events is append-only (% rejected)', TG_OP USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS events_update_updated_at ON public.events;  -- updates are no longer possible
DROP TRIGGER IF EXISTS events_no_update_delete ON public.events;
DROP TRIGGER IF EXISTS events_no_truncate ON public.events;
CREATE TRIGGER events_no_update_delete BEFORE UPDATE OR DELETE ON public.events
  FOR EACH ROW EXECUTE FUNCTION public.events_append_only();
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON public.events
  FOR EACH STATEMENT EXECUTE FUNCTION public.events_append_only();

CREATE OR REPLACE FUNCTION public.archive_events(p_before TIMESTAMPTZ)
RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_moved BIGINT;
BEGIN
  PERFORM set_config('phantom.archiving', 'on', true);  -- transaction-local
  WITH moved AS (
    DELETE FROM public.events WHERE created_at < p_before
    RETURNING id, entity_id, event_type, payload, workspace_id, created_by, created_at
  ), ins AS (
    INSERT INTO public.events_archive (id, entity_id, event_type, payload, workspace_id, created_by, created_at)
    SELECT id, entity_id, event_type, payload, workspace_id, created_by, created_at FROM moved
    RETURNING 1
  )
  SELECT count(*) INTO v_moved FROM ins;
  RETURN v_moved;
END;
$$;
REVOKE ALL ON FUNCTION public.archive_events(TIMESTAMPTZ) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.archive_events(TIMESTAMPTZ) TO service_role;

COMMENT ON TABLE public.events IS 'Append-only event store. UPDATE/DELETE/TRUNCATE rejected by trigger; archive_events() is the only way rows leave.';

-- ============================================================
-- 5. Privilege escalation in 02: add_workspace_user() was SECURITY DEFINER, granted to every
--    authenticated user, and checked nothing. Any user could add themselves as 'owner' of any
--    workspace and then read its events. Reproduced on PostgreSQL 16 before this fix.
--    Now: caller must be owner/admin of the workspace; only an owner may grant 'owner'.
--    All SECURITY DEFINER functions get a pinned search_path.
-- ============================================================
CREATE OR REPLACE FUNCTION public.add_workspace_user(
  p_workspace_id UUID,
  p_user_email VARCHAR,
  p_role VARCHAR DEFAULT 'member'
)
RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user_id UUID;
  v_caller_role VARCHAR;
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'authentication required' USING ERRCODE = 'insufficient_privilege';
  END IF;

  SELECT role INTO v_caller_role FROM public.workspace_users
  WHERE workspace_id = p_workspace_id AND user_id = auth.uid();

  IF v_caller_role IS NULL OR v_caller_role NOT IN ('owner', 'admin') THEN
    RAISE EXCEPTION 'only a workspace owner or admin can add members' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF p_role = 'owner' AND v_caller_role <> 'owner' THEN
    RAISE EXCEPTION 'only a workspace owner can grant the owner role' USING ERRCODE = 'insufficient_privilege';
  END IF;

  SELECT id INTO v_user_id FROM auth.users WHERE email = p_user_email;
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'User not found: %', p_user_email;
  END IF;

  INSERT INTO public.workspace_users (workspace_id, user_id, role)
  VALUES (p_workspace_id, v_user_id, p_role)
  ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = EXCLUDED.role
  WHERE public.workspace_users.role <> 'owner' OR v_caller_role = 'owner';  -- an admin cannot demote an owner
END;
$$;
REVOKE ALL ON FUNCTION public.add_workspace_user(UUID, VARCHAR, VARCHAR) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.add_workspace_user(UUID, VARCHAR, VARCHAR) TO authenticated;

ALTER FUNCTION public.create_workspace(VARCHAR, TEXT) SET search_path = public, pg_temp;
REVOKE ALL ON FUNCTION public.create_workspace(VARCHAR, TEXT) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.create_workspace(VARCHAR, TEXT) TO authenticated;
