-- ============================================================
-- Phantom Runtime - Supabase Database Migrations
-- ============================================================

-- 01_init_events.sql
-- Initialize core event store tables

-- ============================================================
-- 1. Events Table (Immutable Event Log)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.events (
  id BIGSERIAL PRIMARY KEY,
  entity_id VARCHAR(255) NOT NULL,
  event_type VARCHAR(100) NOT NULL,
  payload JSONB NOT NULL,
  workspace_id UUID NOT NULL,
  created_by UUID,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_events_entity_created 
  ON public.events(entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_workspace_id 
  ON public.events(workspace_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type 
  ON public.events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_created_by 
  ON public.events(created_by);

-- Add comment
COMMENT ON TABLE public.events IS 'Immutable event store - core of event sourcing pattern';

-- ============================================================
-- 2. Event Archive (for old events)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.events_archive (
  id BIGSERIAL PRIMARY KEY,
  entity_id VARCHAR(255) NOT NULL,
  event_type VARCHAR(100) NOT NULL,
  payload JSONB NOT NULL,
  workspace_id UUID NOT NULL,
  created_by UUID,
  created_at TIMESTAMP WITH TIME ZONE,
  archived_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_archive_created_at 
  ON public.events_archive(created_at DESC);

-- ============================================================
-- 3. Enable RLS on Events
-- ============================================================
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.events_archive ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 4. Create RLS Policies for Events
-- ============================================================

-- Policy: Users can view events from their workspace
CREATE POLICY "Users can view workspace events"
  ON public.events FOR SELECT
  USING (
    workspace_id IN (
      SELECT workspace_id FROM public.workspace_users 
      WHERE user_id = auth.uid()
    )
  );

-- Policy: Authenticated users can insert events in their workspace
CREATE POLICY "Users can insert events in their workspace"
  ON public.events FOR INSERT
  WITH CHECK (
    workspace_id IN (
      SELECT workspace_id FROM public.workspace_users 
      WHERE user_id = auth.uid()
    )
  );

-- Service role can bypass RLS
ALTER TABLE public.events DISABLE ROW LEVEL SECURITY;

-- ============================================================
-- 5. Functions for Event Management
-- ============================================================

-- Function: Get recent events for entity
CREATE OR REPLACE FUNCTION public.get_entity_events(
  p_entity_id VARCHAR,
  p_workspace_id UUID,
  p_limit INT DEFAULT 100
)
RETURNS TABLE (
  id BIGINT,
  entity_id VARCHAR,
  event_type VARCHAR,
  payload JSONB,
  created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
  RETURN QUERY
  SELECT e.id, e.entity_id, e.event_type, e.payload, e.created_at
  FROM public.events e
  WHERE e.entity_id = p_entity_id 
    AND e.workspace_id = p_workspace_id
  ORDER BY e.created_at DESC
  LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Function: Get event count
CREATE OR REPLACE FUNCTION public.get_event_count(
  p_entity_id VARCHAR,
  p_workspace_id UUID
)
RETURNS BIGINT AS $$
DECLARE
  v_count BIGINT;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM public.events
  WHERE entity_id = p_entity_id 
    AND workspace_id = p_workspace_id;
  RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 6. Trigger for Updated_At
-- ============================================================
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_update_updated_at
  BEFORE UPDATE ON public.events
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at();

-- ============================================================
-- Grants
-- ============================================================
GRANT SELECT, INSERT ON public.events TO authenticated;
GRANT SELECT ON public.events TO anon;
GRANT EXECUTE ON FUNCTION public.get_entity_events TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_event_count TO authenticated;
