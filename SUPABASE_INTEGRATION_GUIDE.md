# Phantom Runtime + Supabase Integration Guide

**Complete guide for deploying Phantom Runtime with Supabase backend**

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Supabase Setup](#supabase-setup)
3. [Database Migration](#database-migration)
4. [Authentication](#authentication)
5. [Frontend Integration](#frontend-integration)
6. [Backend Integration](#backend-integration)
7. [Real-time Features](#real-time-features)
8. [Deployment](#deployment)
9. [Monitoring](#monitoring)
10. [Cost Optimization](#cost-optimization)

---

## Prerequisites

### Required Tools
- Node.js 18+ (frontend)
- Python 3.9+ (backend)
- Git
- Docker (optional, for local testing)

### Required Accounts
- Supabase account (free tier available at https://supabase.com)
- GitHub account (recommended)

### Knowledge
- Basic SQL
- PostgreSQL concepts
- REST API concepts
- JavaScript/TypeScript basics (for frontend)

---

## Supabase Setup

### Step 1: Create Supabase Project

1. Go to https://app.supabase.com
2. Click **New Project**
3. Fill in project details:
   - **Name:** phantom-runtime-demo
   - **Database Password:** Choose secure password
   - **Region:** Closest to your users
4. Click **Create new project** (takes ~2 minutes)

### Step 2: Get Project Credentials

Once project is created:

1. Go to **Settings > API**
2. Copy these values:
   ```
   Project URL:           https://[PROJECT_ID].supabase.co
   Anon Public Key:       eyJhbGc...
   Service Role Secret:   eyJhbGc...
   ```

3. Go to **Settings > Database**
4. Copy connection string

### Step 3: Environment Setup

Create `.env.supabase` in project root:

```bash
# Supabase API
SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY

# Database (for migrations)
SUPABASE_DB_URL=postgresql://postgres:PASSWORD@db.YOUR_PROJECT_ID.supabase.co:5432/postgres

# Frontend
VITE_SUPABASE_URL=https://YOUR_PROJECT_ID.supabase.co
VITE_SUPABASE_ANON_KEY=YOUR_ANON_KEY

# Backend
DATABASE_URL=postgresql://postgres:PASSWORD@db.YOUR_PROJECT_ID.supabase.co:5432/postgres
```

---

## Database Migration

### Option 1: Using SQL Editor (Recommended for Testing)

1. Go to Supabase Dashboard
2. Click **SQL Editor** in left sidebar
3. Create new query
4. Copy-paste entire migration file:
   ```bash
   cat supabase/migrations/01_init_events.sql
   ```
5. Click **Run**
6. Repeat for `02_init_workspaces.sql`

### Option 2: Using Supabase CLI (Recommended for Production)

```bash
# Install CLI
npm install -g supabase

# Login
supabase login

# Link project
supabase link --project-id YOUR_PROJECT_ID

# Apply migrations
supabase db push

# Verify tables
supabase db list
```

### Step 3: Verify Migrations

In Supabase Dashboard, go to **Table Editor**:

✅ Should see tables:
- `events`
- `events_archive`
- `workspaces`
- `workspace_users`
- `api_keys`
- `defi_events` (if created)
- `snapshots` (if created)

---

## Authentication

### Enable Email Authentication

1. Go to **Authentication > Providers**
2. Click **Email** provider
3. Toggle **Email** ON
4. Copy SMTP configuration (optional for production)

### Enable OAuth (Optional)

1. Go to **Authentication > Providers**
2. Select provider (Google, GitHub, etc.)
3. Follow provider-specific setup

### Configure Redirect URLs

1. Go to **Authentication > URL Configuration**
2. Add redirect URLs:
   ```
   Development:   http://localhost:3000/auth/callback
   Development:   http://localhost:3000
   Production:    https://yourdomain.com/auth/callback
   Production:    https://yourdomain.com
   ```

---

## Frontend Integration

### Step 1: Install Dependencies

```bash
cd frontend

npm install @supabase/supabase-js
npm install -D @types/node
```

### Step 2: Create Supabase Client

```typescript
// src/lib/supabase.ts
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabase = createClient(supabaseUrl, supabaseKey)
```

### Step 3: Add Auth Context

```typescript
// src/context/AuthContext.tsx
import React, { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

interface AuthContextType {
  user: any
  loading: boolean
  signUp: (email: string, password: string) => Promise<void>
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = React.createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Check auth status on mount
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null)
      setLoading(false)
    })

    // Subscribe to auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        setUser(session?.user ?? null)
      }
    )

    return () => subscription.unsubscribe()
  }, [])

  const signUp = async (email: string, password: string) => {
    const { error } = await supabase.auth.signUp({ email, password })
    if (error) throw error
  }

  const signIn = async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
  }

  const signOut = async () => {
    const { error } = await supabase.auth.signOut()
    if (error) throw error
  }

  return (
    <AuthContext.Provider value={{ user, loading, signUp, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = React.useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
```

### Step 4: Add Login Component

```typescript
// src/components/Login.tsx
import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSignUp, setIsSignUp] = useState(false)
  const { signIn, signUp } = useAuth()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      if (isSignUp) {
        await signUp(email, password)
      } else {
        await signIn(email, password)
      }
    } catch (error) {
      console.error('Auth error:', error)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full space-y-8">
        <h2>{isSignUp ? 'Sign Up' : 'Sign In'}</h2>
        <form onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit">
            {isSignUp ? 'Create Account' : 'Sign In'}
          </button>
        </form>
        <button onClick={() => setIsSignUp(!isSignUp)}>
          {isSignUp ? 'Already have an account?' : 'Create account'}
        </button>
      </div>
    </div>
  )
}
```

---

## Backend Integration

### Step 1: Install Supabase Python Client

```bash
cd backend

pip install supabase
pip install python-dotenv
```

### Step 2: Initialize Supabase Client

```python
# app/core/supabase_client.py
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv('.env.supabase')

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
```

### Step 3: Create Event Service

```python
# app/services/event_service.py
from app.core.supabase_client import supabase
from typing import Any, Dict, List

class EventService:
    @staticmethod
    def create_event(
        workspace_id: str,
        entity_id: str,
        event_type: str,
        payload: Dict[str, Any]
    ) -> Dict:
        response = supabase.table('events').insert([{
            'workspace_id': workspace_id,
            'entity_id': entity_id,
            'event_type': event_type,
            'payload': payload
        }]).execute()
        return response.data[0] if response.data else None

    @staticmethod
    def get_entity_events(
        workspace_id: str,
        entity_id: str
    ) -> List[Dict]:
        response = supabase.rpc('get_entity_events', {
            'p_entity_id': entity_id,
            'p_workspace_id': workspace_id,
            'p_limit': 100
        }).execute()
        return response.data or []

    @staticmethod
    def reconstruct_state(events: List[Dict]) -> Dict[str, Any]:
        state = {}
        for event in sorted(events, key=lambda e: e.get('created_at', '')):
            if event['event_type'] == 'init':
                state = event['payload'].copy()
            elif event['event_type'] == 'update':
                state.update(event['payload'])
            elif event['event_type'] == 'delete_field':
                for field in event['payload'].get('fields', []):
                    state.pop(field, None)
            elif event['event_type'] == 'reset':
                state = {}
        return state
```

### Step 4: Create API Routes

```python
# app/api/routes_events_supabase.py
from fastapi import APIRouter, HTTPException
from app.services.event_service import EventService
from pydantic import BaseModel

router = APIRouter(prefix='/api/events', tags=['events'])

class CreateEventRequest(BaseModel):
    entity_id: str
    event_type: str
    payload: dict

@router.post('/')
async def create_event(workspace_id: str, request: CreateEventRequest):
    try:
        event = EventService.create_event(
            workspace_id,
            request.entity_id,
            request.event_type,
            request.payload
        )
        return event
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get('/{entity_id}')
async def get_entity_events(workspace_id: str, entity_id: str):
    events = EventService.get_entity_events(workspace_id, entity_id)
    state = EventService.reconstruct_state(events)
    return {
        'entity_id': entity_id,
        'state': state,
        'event_count': len(events)
    }
```

---

## Real-time Features

### Frontend Real-time Subscription

```typescript
// src/hooks/useRealtimeEvents.ts
import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

export function useRealtimeEvents(workspaceId: string) {
  const [events, setEvents] = useState<any[]>([])

  useEffect(() => {
    // Subscribe to new events
    const subscription = supabase
      .from(`events:workspace_id=eq.${workspaceId}`)
      .on('INSERT', ({ new: newEvent }) => {
        setEvents(prev => [newEvent, ...prev])
      })
      .subscribe()

    return () => supabase.removeSubscription(subscription)
  }, [workspaceId])

  return events
}
```

### Use in Component

```typescript
// src/components/EventStream.tsx
import { useRealtimeEvents } from '../hooks/useRealtimeEvents'

export function EventStream({ workspaceId }: { workspaceId: string }) {
  const events = useRealtimeEvents(workspaceId)

  return (
    <div>
      <h2>Real-time Events</h2>
      {events.map(event => (
        <div key={event.id}>
          <strong>{event.event_type}</strong>: {event.entity_id}
          <pre>{JSON.stringify(event.payload, null, 2)}</pre>
        </div>
      ))}
    </div>
  )
}
```

---

## Deployment

### Deploy to Vercel (Frontend)

```bash
cd frontend

# Install Vercel CLI
npm install -g vercel

# Deploy
vercel

# Set environment variables
vercel env add VITE_SUPABASE_URL
vercel env add VITE_SUPABASE_ANON_KEY

# Redeploy
vercel --prod
```

### Deploy to Railway/Fly.io (Backend)

```bash
cd backend

# Using Railway
railway link
railway up

# Using Fly.io
fly auth login
fly launch
fly deploy
```

### Environment Variables

Set these in deployment platform:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DATABASE_URL`
- `CORS_ORIGINS`
- `JWT_SECRET`

---

## Monitoring

### Supabase Dashboard Metrics

- **Analytics:** Query performance, API usage
- **Database:** Query logs, table sizes
- **Auth:** Login attempts, user growth
- **Storage:** File uploads, bandwidth

### Set Alerts

1. Go to **Monitoring**
2. Create alerts for:
   - High query latency (>100ms)
   - Failed authentications
   - Storage usage >80%
   - Bandwidth usage >90%

---

## Cost Optimization

### Supabase Pricing

| Metric | Free | Pro |
|--------|------|-----|
| Database | 500 MB | 8 GB |
| Bandwidth | 2 GB | 50 GB |
| Storage | 1 GB | 100 GB |
| Cost | $0 | $25/mo |

### Optimization Tips

1. **Indexing:** Use provided indexes
2. **Connection Pooling:** Enable PgBouncer
3. **Caching:** Add Redis layer
4. **Archiving:** Move old events to `events_archive`
5. **Cleanup:** Remove unused workspaces

---

## Troubleshooting

### Connection Errors

```bash
# Test connection
psql postgresql://postgres:PASSWORD@db.PROJECT_ID.supabase.co:5432/postgres

# Check firewall
# Supabase allows all IPs by default
```

### Auth Issues

- Check redirect URLs in **Authentication > URL Configuration**
- Verify email confirmed in Supabase console
- Check JWT secret in backend

### Real-time Not Working

- Enable real-time in **Replication** for specific tables
- Verify table has replica identity set to FULL
- Check browser WebSocket connections

### Performance Issues

- Check indexes with `EXPLAIN ANALYZE`
- Use connection pooling (port 6543)
- Archive old events
- Add caching layer

---

## Next Steps

1. ✅ Create Supabase project
2. ✅ Run migrations
3. ✅ Set up authentication
4. ✅ Integrate frontend
5. ✅ Integrate backend
6. ✅ Test real-time
7. ✅ Deploy to production
8. ✅ Set up monitoring
9. ✅ Optimize costs

---

## Support & Resources

- **Supabase Docs:** https://supabase.com/docs
- **Phantom Runtime Repo:** [GitHub]
- **Supabase Discord:** https://discord.supabase.com
- **Issues:** GitHub Issues

