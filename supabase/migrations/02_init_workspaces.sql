-- 02_init_workspaces.sql
-- Initialize multi-tenancy support

-- ============================================================
-- 1. Workspaces Table
-- ============================================================
CREATE TABLE IF NOT EXISTS public.workspaces (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  settings JSONB DEFAULT '{"tier": "free", "features": []}'::jsonb,
  status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'archived', 'suspended'))
);

CREATE INDEX IF NOT EXISTS idx_workspaces_owner_id 
  ON public.workspaces(owner_id);

-- ============================================================
-- 2. Workspace Users (Many-to-Many)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.workspace_users (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role VARCHAR(50) NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  UNIQUE(workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_users_workspace_id 
  ON public.workspace_users(workspace_id);
CREATE INDEX IF NOT EXISTS idx_workspace_users_user_id 
  ON public.workspace_users(user_id);

-- ============================================================
-- 3. API Keys Table
-- ============================================================
CREATE TABLE IF NOT EXISTS public.api_keys (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  key_hash VARCHAR(255) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  last_used_at TIMESTAMP WITH TIME ZONE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  expires_at TIMESTAMP WITH TIME ZONE,
  is_active BOOLEAN DEFAULT TRUE,
  permissions JSONB DEFAULT '["read", "write"]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_api_keys_workspace_id 
  ON public.api_keys(workspace_id);

-- ============================================================
-- 4. RLS for Workspaces
-- ============================================================
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;

-- Policies for workspaces
CREATE POLICY "Users can view their workspaces"
  ON public.workspaces FOR SELECT
  USING (
    id IN (
      SELECT workspace_id FROM public.workspace_users 
      WHERE user_id = auth.uid()
    )
    OR owner_id = auth.uid()
  );

CREATE POLICY "Users can update their workspace"
  ON public.workspaces FOR UPDATE
  USING (owner_id = auth.uid());

-- Policies for workspace_users
CREATE POLICY "Users can view workspace members"
  ON public.workspace_users FOR SELECT
  USING (
    workspace_id IN (
      SELECT workspace_id FROM public.workspace_users 
      WHERE user_id = auth.uid()
    )
  );

-- ============================================================
-- 5. Functions for Workspace Management
-- ============================================================

-- Create workspace
CREATE OR REPLACE FUNCTION public.create_workspace(
  p_name VARCHAR,
  p_description TEXT
)
RETURNS UUID AS $$
DECLARE
  v_workspace_id UUID;
BEGIN
  INSERT INTO public.workspaces (name, description, owner_id)
  VALUES (p_name, p_description, auth.uid())
  RETURNING id INTO v_workspace_id;

  -- Add owner as workspace member
  INSERT INTO public.workspace_users (workspace_id, user_id, role)
  VALUES (v_workspace_id, auth.uid(), 'owner');

  RETURN v_workspace_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Add user to workspace
CREATE OR REPLACE FUNCTION public.add_workspace_user(
  p_workspace_id UUID,
  p_user_email VARCHAR,
  p_role VARCHAR DEFAULT 'member'
)
RETURNS VOID AS $$
DECLARE
  v_user_id UUID;
BEGIN
  -- Get user by email
  SELECT id INTO v_user_id 
  FROM auth.users 
  WHERE email = p_user_email;

  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'User not found: %', p_user_email;
  END IF;

  INSERT INTO public.workspace_users (workspace_id, user_id, role)
  VALUES (p_workspace_id, v_user_id, p_role)
  ON CONFLICT (workspace_id, user_id) DO UPDATE
  SET role = EXCLUDED.role;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get workspace stats
CREATE OR REPLACE FUNCTION public.get_workspace_stats(p_workspace_id UUID)
RETURNS TABLE (
  workspace_name VARCHAR,
  member_count BIGINT,
  event_count BIGINT,
  storage_bytes BIGINT
) AS $$
BEGIN
  RETURN QUERY
  SELECT 
    w.name,
    (SELECT COUNT(*) FROM public.workspace_users WHERE workspace_id = p_workspace_id)::BIGINT,
    (SELECT COUNT(*) FROM public.events WHERE workspace_id = p_workspace_id)::BIGINT,
    (SELECT pg_total_relation_size('public.events'))::BIGINT
  FROM public.workspaces w
  WHERE w.id = p_workspace_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 6. Grants
-- ============================================================
GRANT SELECT, INSERT ON public.workspaces TO authenticated;
GRANT SELECT, INSERT ON public.workspace_users TO authenticated;
GRANT SELECT ON public.api_keys TO authenticated;
GRANT EXECUTE ON FUNCTION public.create_workspace TO authenticated;
GRANT EXECUTE ON FUNCTION public.add_workspace_user TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_workspace_stats TO authenticated;
