-- 04_security_followup.sql
-- Follow-up to 03, applied to icomply-db after 03:
--   * anon could still execute is_workspace_member (Supabase grants anon directly, so REVOKE FROM PUBLIC is not enough).
--   * Pin search_path on remaining functions flagged by the security advisor.
-- Idempotent.
REVOKE EXECUTE ON FUNCTION public.is_workspace_member(uuid) FROM anon;
ALTER FUNCTION public.events_append_only() SET search_path = public, pg_temp;
ALTER FUNCTION public.update_updated_at() SET search_path = public, pg_temp;
ALTER FUNCTION public.get_event_count SET search_path = public, pg_temp;
ALTER FUNCTION public.get_entity_events SET search_path = public, pg_temp;
ALTER FUNCTION public.get_workspace_stats SET search_path = public, pg_temp;
