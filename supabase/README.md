# Supabase Configuration for Phantom Runtime

This file contains all necessary Supabase configuration and setup instructions.

## Environment Variables

Create a `.env.supabase` file with the following:

```bash
# Supabase Project Configuration
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key-here

# Backend API Configuration
SUPABASE_POSTGRES_URL=postgresql://postgres:[PASSWORD]@db.your-project-id.supabase.co:5432/postgres
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.your-project-id.supabase.co:5432/postgres

# Frontend Configuration
VITE_SUPABASE_URL=https://your-project-id.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key-here

# Authentication
SUPABASE_JWT_SECRET=your-jwt-secret-here

# Optional: Webhook Configuration
SUPABASE_WEBHOOK_SIGNING_SECRET=your-webhook-secret-here
```

## Getting Your Credentials

1. Go to https://app.supabase.com
2. Create a new project or select existing
3. Navigate to **Settings > API**
4. Copy:
   - Project URL → `SUPABASE_URL`
   - Anon Public key → `SUPABASE_ANON_KEY`
   - Service Role key → `SUPABASE_SERVICE_ROLE_KEY`
   - JWT Secret → `SUPABASE_JWT_SECRET`

5. For database URL:
   - Go to **Settings > Database**
   - Copy connection string
   - Replace `[PASSWORD]` with your database password

## Directory Structure

```
supabase/
├── migrations/              # SQL migration files
│   ├── 01_init_events.sql
│   ├── 02_init_snapshots.sql
│   ├── 03_init_workspaces.sql
│   ├── 04_init_plugins.sql
│   └── 05_init_defi.sql
├── seeds/                   # Seed data scripts
│   └── seed-demo-data.sql
├── functions/               # Edge Functions
│   ├── event-processor.ts
│   └── state-reconstructor.ts
├── policies/                # Row Level Security (RLS)
│   ├── events_rls.sql
│   └── workspaces_rls.sql
├── config.json              # Supabase project config
└── README.md                # This file
```

## Quick Start

### Option 1: Using Supabase CLI (Recommended)

```bash
# Install Supabase CLI
npm install -g supabase

# Login to Supabase
supabase login

# Link to your project
supabase link --project-id YOUR_PROJECT_ID

# Apply migrations
supabase db push

# Seed demo data
psql $DATABASE_URL < supabase/seeds/seed-demo-data.sql

# Deploy Edge Functions
supabase functions deploy
```

### Option 2: Manual Setup via Web Console

1. Go to https://app.supabase.com
2. Select your project
3. Go to **SQL Editor**
4. Create new query
5. Copy-paste migrations from `supabase/migrations/` files
6. Execute each migration

## Database Schema Overview

### Tables Created

| Table | Purpose | Rows |
|-------|---------|------|
| `events` | Immutable event log | Core |
| `snapshots` | State snapshots | Optimization |
| `workspaces` | Multi-tenant workspaces | Isolation |
| `workspace_users` | User-workspace mapping | Access |
| `api_keys` | API key management | Security |
| `defi_events` | DeFi-specific events | Domain |
| `plugins` | Plugin registry | Extension |
| `audit_logs` | Compliance logging | Audit |

### Row Level Security (RLS)

All tables have RLS enabled by default:
- Users can only access their workspace data
- Service role can bypass RLS
- Workspace owners have full access

## Authentication

### Supabase Auth Integration

Phantom Runtime supports both:
1. **Email/Password** - Traditional username/password
2. **OAuth Providers** - Google, GitHub, Azure, etc.
3. **JWT Tokens** - For API integration

### Setting Up Auth

1. Go to **Authentication > Providers**
2. Enable desired providers
3. Configure redirect URLs:
   - Development: `http://localhost:3000/auth/callback`
   - Production: `https://yourdomain.com/auth/callback`

## Real-time Subscriptions

Supabase provides real-time database changes:

```javascript
// Subscribe to new events
const subscription = supabase
  .from('events')
  .on('INSERT', (payload) => {
    console.log('New event:', payload.new)
  })
  .subscribe()

// Unsubscribe when done
supabase.removeSubscription(subscription)
```

## Backup & Recovery

### Automatic Backups

Supabase provides daily backups on Pro+ plans.

### Manual Backup

```bash
# Backup entire database
pg_dump $DATABASE_URL > backup.sql

# Restore from backup
psql $DATABASE_URL < backup.sql
```

## Performance Optimization

### Recommended Indexes

Already created in migrations:
- `idx_events_entity_created` - For event queries
- `idx_workspace_users_workspace_id` - For workspace access
- `idx_api_keys_workspace_id` - For key lookups

### Connection Pooling

Supabase provides connection pooling via PgBouncer. Use:
```
postgresql://user:password@db.supabase.co:6543/postgres
```
(Port 6543 instead of 5432)

## Monitoring

### Supabase Dashboard Metrics

- Go to **Project > Analytics** to view:
  - Query performance
  - Storage usage
  - Bandwidth consumption
  - Error logs

### Performance Monitoring

```sql
-- Check slow queries
SELECT * FROM pg_stat_statements 
ORDER BY total_time DESC 
LIMIT 10;

-- Check table sizes
SELECT 
  tablename,
  pg_size_pretty(pg_total_relation_size(tablename)) 
FROM pg_tables 
WHERE tablename NOT LIKE 'pg_%'
ORDER BY pg_total_relation_size(tablename) DESC;
```

## Cost Optimization

### Supabase Pricing Tiers

| Plan | Storage | Bandwidth | Cost |
|------|---------|-----------|------|
| Free | 500 MB | 2 GB | $0 |
| Pro | 8 GB | 50 GB | $25/mo |
| Business | 200 GB | Unlimited | Custom |

### Tips for Free Tier

- Use connection pooling
- Implement caching
- Archive old events
- Clean up unused data

## Troubleshooting

### Connection Issues

```bash
# Test connection
psql $DATABASE_URL -c "SELECT 1"

# Check connection string format
postgresql://user:password@host:port/database
```

### RLS Issues

If queries fail:
1. Check RLS policies in **Authentication > Policies**
2. Verify user has correct role
3. Test with service role key

### Real-time Not Working

1. Check real-time is enabled in **Database > Replication**
2. Verify table has replica identity set to FULL
3. Check browser console for errors

## Next Steps

1. ✅ Copy credentials to `.env.supabase`
2. ✅ Run migrations from `supabase/migrations/`
3. ✅ Seed demo data
4. ✅ Configure authentication
5. ✅ Test real-time subscriptions
6. ✅ Review RLS policies

## Support

- **Supabase Docs:** https://supabase.com/docs
- **Supabase Discord:** https://discord.supabase.com
- **GitHub Issues:** Open issue on Phantom Runtime repo
