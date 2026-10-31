-- Enable row level security on every application table.
-- The app connects through Prisma as the table owner, which bypasses RLS, so behavior is unchanged.
-- Any other role (for example Supabase anon/authenticated via PostgREST) is denied by default until a policy is added.
ALTER TABLE "MonitoredSite" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "ChangeLog" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "WebhookEndpoint" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "WebhookDelivery" ENABLE ROW LEVEL SECURITY;
