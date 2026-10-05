# Phantom Runtime + Supabase - Complete Demo Guide

**A step-by-step guide to running the full Phantom Runtime demo with Supabase backend**

---

## 📋 Demo Overview

This guide walks you through:
1. Setting up Supabase project
2. Creating database schema
3. Seeding demo data
4. Running frontend demo
5. Running backend demo
6. Testing real-time features
7. Monitoring and optimization

**Time Required:** ~30-45 minutes (first run)

---

## Phase 1: Supabase Setup (5-10 minutes)

### Step 1.1: Create Supabase Project

```bash
# Go to https://app.supabase.com
# Click "New Project"
# Fill in:
#   Name: phantom-runtime-demo
#   Database Password: [generate secure password]
#   Region: [closest to you]
# Wait for project creation (2-3 minutes)
```

### Step 1.2: Get Credentials

```bash
# After project created, navigate to Settings > API
# Copy these:
SUPABASE_URL = https://[PROJECT_ID].supabase.co
SUPABASE_ANON_KEY = eyJhbGciOiJIUzI1NiIsInR5cCI...
SUPABASE_SERVICE_ROLE_KEY = eyJhbGciOiJIUzI1NiIsInR5cCI...

# Go to Settings > Database > Connection string
# Copy connection string (replace [PASSWORD] with your database password)
SUPABASE_DB_URL = postgresql://postgres:[PASSWORD]@db.[PROJECT_ID].supabase.co:5432/postgres
```

### Step 1.3: Create Environment File

```bash
# In phantom-runtime directory
cat > .env.supabase << EOF
SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY_HERE
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY_HERE
SUPABASE_DB_URL=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_ID.supabase.co:5432/postgres
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_ID.supabase.co:5432/postgres
VITE_SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
VITE_SUPABASE_ANON_KEY=YOUR_ANON_KEY_HERE
EOF
```

---

## Phase 2: Database Migration (5-10 minutes)

### Step 2.1: Option A - Using SQL Editor (Easiest)

```bash
# Open Supabase Dashboard
# Go to SQL Editor
# Click "New Query"
# Copy-paste content from supabase/migrations/01_init_events.sql
# Click "Run"
# Repeat for supabase/migrations/02_init_workspaces.sql
```

### Step 2.2: Option B - Using CLI (Recommended)

```bash
# Install Supabase CLI
npm install -g supabase

# Login
supabase login
# Follow browser prompts

# Link project
supabase link --project-id YOUR_PROJECT_ID

# Push migrations
supabase db push

# Verify
supabase db list
```

### Step 2.3: Verify Tables

```bash
# In Supabase Dashboard, go to Table Editor
# Should see:
✅ events
✅ events_archive
✅ workspaces
✅ workspace_users
✅ api_keys
```

---

## Phase 3: Seed Demo Data (2-3 minutes)

### Step 3.1: Create Workspace

```bash
# In Supabase Dashboard, go to SQL Editor
# Click "New Query"
# Run this to get your user ID:
SELECT id FROM auth.users LIMIT 1;

# Copy the ID, then update supabase/seeds/demo-data.sql
# Replace:
#   auth.uid() with your actual user ID
#   '550e8400-e29b-41d4-a716-446655440000' with your workspace_id
```

### Step 3.2: Load Demo Data

```bash
# Execute demo data script
psql $SUPABASE_DB_URL < supabase/seeds/demo-data.sql

# Or paste in SQL Editor and run
```

### Step 3.3: Verify Data

```bash
# In SQL Editor, run:
SELECT COUNT(*) as total_events FROM public.events;
SELECT COUNT(*) as total_defi_trades FROM public.defi_events;
SELECT COUNT(*) as total_snapshots FROM public.snapshots;

# Should see counts > 0
```

---

## Phase 4: Frontend Demo (5-10 minutes)

### Step 4.1: Install Dependencies

```bash
cd phantom-runtime/frontend

npm install @supabase/supabase-js

# Create .env.local
cat > .env.local << EOF
VITE_SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
VITE_SUPABASE_ANON_KEY=YOUR_ANON_KEY_HERE
EOF
```

### Step 4.2: Run Demo

```bash
# Method 1: Use demo TypeScript file
npx ts-node ../supabase-demo.ts

# Method 2: Create demo page
# Copy code from supabase-demo.ts to src/pages/SupabaseDemo.tsx
# Add route and visit http://localhost:3000/supabase-demo

# Start dev server
npm run dev

# Open browser console (F12)
# Check console output
```

### Step 4.3: Test Features

```javascript
// In browser console:

// 1. Sign up
await demoSignUp('demo@phantom.local', 'Demo123!@#')

// 2. Create workspace
const workspaceId = await demoCreateWorkspace(
  'My First Workspace',
  'Testing Phantom with Supabase'
)

// 3. Create event
await demoCreateEvent(
  workspaceId,
  'user_001',
  'init',
  { name: 'Alice', balance: 1000 }
)

// 4. Get events
const events = await demoGetEntityEvents(workspaceId, 'user_001')

// 5. Reconstruct state
const state = await demoReconstructState(events)
console.log('State:', state)

// 6. Subscribe to real-time
const subscription = demoSubscribeToEvents(workspaceId)

// 7. Create DeFi event
await demoCreateDeFiEvent(
  workspaceId,
  'trader_001',
  'deposit',
  'ETH',
  10,
  3500
)

// 8. Get portfolio
const portfolio = await demoGetTraderPortfolio(workspaceId, 'trader_001')
console.log('Portfolio:', portfolio)
```

**Expected Output:**
```
✅ User created: demo@phantom.local
✅ Workspace created, ID: [uuid]
✅ Event created: [id]
✅ Found events: 1
✅ State reconstructed: {"name":"Alice","balance":1000}
✅ Subscribed to events
✅ DeFi event created: [id]
✅ Portfolio: {portfolio: {ETH: 10}, totalValue: 35000}
```

---

## Phase 5: Backend Demo (5-10 minutes)

### Step 5.1: Install Dependencies

```bash
cd phantom-runtime/backend

pip install supabase python-dotenv

# Create .env file with Supabase credentials
cp ../.env.supabase .env
```

### Step 5.2: Run Backend Demo

```bash
# Run demo script
python ../supabase-backend-demo.py

# Or run in Python shell:
python -i -c "from supabase_backend_demo import *; import asyncio"

# Then:
>>> asyncio.run(run_backend_demo())
```

**Expected Output:**
```
🚀 Starting Phantom Runtime Backend Demo (Supabase)

🔐 Authenticating as service role...
✅ Service role authenticated

📝 Creating event: init for user_123...
✅ Event created: [id]

📖 Fetching events for user_123...
✅ Found events: 1

🔨 Reconstructing state from 1 events...
✅ State reconstructed: {"name":"Alice","balance":1000,"status":"active"}

📸 Creating snapshot for user_123...
✅ Snapshot created

⚡ Fast recovery for user_123...
✅ Fast recovery complete

💰 Creating DeFi event: deposit 10 ETH...
✅ DeFi event created

💼 Fetching trader portfolio...
✅ Portfolio: {'ETH': 10}

📊 Getting workspace stats...
✅ Stats: {...}

✅ Backend demo completed successfully!
```

### Step 5.3: API Testing

```bash
# Test with curl
curl http://localhost:8001/api/health

# Create event
curl -X POST http://localhost:8001/api/events/ \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
    "entity_id": "user_123",
    "event_type": "init",
    "payload": {"name": "Test", "value": 100}
  }'

# Get state
curl http://localhost:8001/api/state/user_123
```

---

## Phase 6: Real-time Features (5 minutes)

### Step 6.1: Real-time Subscriptions

```typescript
// Frontend
const subscription = supabase
  .from('events:workspace_id=eq.550e8400-e29b-41d4-a716-446655440000')
  .on('INSERT', (payload) => {
    console.log('📨 New event:', payload.new)
  })
  .subscribe()
```

### Step 6.2: Test Real-time

```javascript
// In one browser tab/console
// Subscribe to events
const subscription = demoSubscribeToEvents(workspaceId)

// In another tab/console or backend
// Create event
await demoCreateEvent(workspaceId, 'user_rt_test', 'init', {test: 'realtime'})

// First tab should show:
// 📨 New event: {...}
```

### Step 6.3: Real-time Metrics

```bash
# In Supabase Dashboard
# Go to Monitoring > Database Metrics
# You should see:
# - Real-time connections: 1+
# - Event throughput: Active
# - Message latency: <100ms
```

---

## Phase 7: Monitoring & Optimization (5 minutes)

### Step 7.1: Check Dashboard Metrics

```bash
# Supabase Dashboard > Analytics
# View:
✅ API requests
✅ Auth events
✅ Database queries
✅ Storage usage
```

### Step 7.2: Performance Monitoring

```sql
-- Check slow queries
SELECT * FROM pg_stat_statements 
ORDER BY total_time DESC 
LIMIT 5;

-- Check table sizes
SELECT 
  tablename,
  pg_size_pretty(pg_total_relation_size(tablename)) AS size
FROM pg_tables 
WHERE tablename NOT LIKE 'pg_%'
ORDER BY pg_total_relation_size(tablename) DESC;
```

### Step 7.3: Set Alerts

```bash
# In Supabase Dashboard
# Go to Monitoring > Alerts
# Create alerts for:
# ✅ Query latency > 100ms
# ✅ Failed authentications > 10
# ✅ Storage usage > 80%
```

---

## Phase 8: Cleanup (2 minutes)

### Step 8.1: Archive Old Data

```sql
-- Move old events to archive
INSERT INTO public.events_archive
SELECT * FROM public.events
WHERE created_at < NOW() - INTERVAL '30 days';

-- Delete archived events
DELETE FROM public.events
WHERE created_at < NOW() - INTERVAL '30 days';
```

### Step 8.2: Verify Cleanup

```sql
SELECT COUNT(*) FROM public.events;
SELECT COUNT(*) FROM public.events_archive;
```

---

## 🧪 Testing Checklist

### Frontend Tests
- [ ] Sign up works
- [ ] Sign in works
- [ ] Create workspace works
- [ ] Create event works
- [ ] Get events works
- [ ] State reconstruction works
- [ ] Real-time subscription works
- [ ] DeFi event creation works
- [ ] Portfolio query works

### Backend Tests
- [ ] Service role authentication works
- [ ] Create event works
- [ ] Get entity events works
- [ ] State reconstruction works
- [ ] Create snapshot works
- [ ] Fast recovery works
- [ ] DeFi events work
- [ ] Get portfolio works
- [ ] Workspace stats work

### Database Tests
- [ ] All tables created
- [ ] Indexes exist
- [ ] RLS policies enabled
- [ ] Functions work
- [ ] Demo data loaded
- [ ] Triggers working

---

## 🐛 Troubleshooting

### Connection Issues

```bash
# Test database connection
psql $SUPABASE_DB_URL -c "SELECT 1"

# Check if migrations applied
psql $SUPABASE_DB_URL -c "\dt"
```

### Auth Issues

```bash
# Check auth configuration
# Supabase Dashboard > Authentication > Providers
# Verify: Email is enabled

# Check redirect URLs
# Supabase Dashboard > Authentication > URL Configuration
# Add: http://localhost:3000/auth/callback
```

### Real-time Not Working

```bash
# Check real-time is enabled
# Supabase Dashboard > Database > Replication
# Toggle ON for tables

# Check browser console for errors
# F12 > Console
# Look for WebSocket connection errors
```

---

## 📊 Demo Data Summary

**Created by seeding script:**
- 1 workspace: "Phantom Finance Demo"
- 3 users: Alice (Trader), Bob (Investor), Carol (Fund Manager)
- 3 portfolios with transactions
- 8 events (init, update, compute)
- 3 DeFi trades
- 3 snapshots
- 2 API keys (full + read-only)

**Total Data:**
- 15+ events
- 3 snapshots
- 3 DeFi trades
- 2+ API keys

---

## 🚀 Next Steps

### Customize the Demo
1. Modify `supabase/seeds/demo-data.sql` with your data
2. Add custom event types
3. Create more complex state transitions
4. Add business logic functions

### Deploy
1. Push frontend to Vercel
2. Deploy backend to Railway/Fly.io
3. Configure production Supabase
4. Set up monitoring/alerts

### Extend Features
1. Add WebSocket for real-time updates
2. Implement caching layer
3. Add analytics dashboards
4. Create audit logging
5. Add compliance reporting

---

## 📚 Reference Documentation

- **Supabase Guide:** `SUPABASE_INTEGRATION_GUIDE.md`
- **Testing Report:** `TESTING_REPORT.md`
- **Metrics Report:** `METRICS_REPORT.md`
- **Quick Reference:** `QUICK_REFERENCE.md`

---

## ✅ Demo Completion

When all phases complete, you'll have:
- ✅ Supabase backend running
- ✅ Database schema created
- ✅ Demo data seeded
- ✅ Frontend working with real-time
- ✅ Backend API functional
- ✅ Event sourcing operational
- ✅ State reconstruction working
- ✅ DeFi features operational
- ✅ Monitoring set up
- ✅ Performance optimized

**You're ready for production deployment! 🎉**

---

**Total Time:** 30-45 minutes  
**Difficulty:** Intermediate  
**Prerequisites:** Node.js, Python, Supabase account

