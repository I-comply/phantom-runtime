-- Prepared rollback for the OPERATIONAL parts of migration 03: the append-only enforcement and
-- archive_events(). Use it only if something legitimate (a job, an edge function) needs to UPDATE or
-- DELETE public.events and cannot be changed in time:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f supabase/rollout/03_rollback.sql
--
-- Deliberately NOT rolled back: RLS (stays enabled), the removal of the anon grant, the
-- add_workspace_user() authorization check, and the non-recursive policies. Reverting those would
-- reopen the holes migration 03 closes (anon reads of every workspace's events, any user making
-- themselves owner of any workspace, workspace queries failing with infinite recursion). If you need
-- the full pre-03 state, restore the backup taken before applying 03 instead.
DROP TRIGGER IF EXISTS events_no_update_delete ON public.events;
DROP TRIGGER IF EXISTS events_no_truncate ON public.events;
DROP FUNCTION IF EXISTS public.archive_events(TIMESTAMPTZ);
DROP FUNCTION IF EXISTS public.events_append_only();

-- 01 had this trigger; 03 dropped it because updates were no longer possible
DROP TRIGGER IF EXISTS events_update_updated_at ON public.events;
CREATE TRIGGER events_update_updated_at
  BEFORE UPDATE ON public.events
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at();

COMMENT ON TABLE public.events IS 'Event store (append-only enforcement rolled back; RLS still on)';
