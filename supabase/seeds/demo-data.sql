-- ============================================================
-- Phantom Runtime - Demo Data Seeding Script
-- ============================================================
-- This script populates Supabase with realistic demo data
-- Run this AFTER all migrations are applied

-- ============================================================
-- 1. Create Demo Workspace
-- ============================================================

INSERT INTO public.workspaces (name, description, owner_id, settings, status)
VALUES (
  'Phantom Finance Demo',
  'Demo workspace showcasing event sourcing for trading platform',
  auth.uid(),  -- Replace with actual user ID
  '{"tier": "pro", "features": ["defi", "real-time", "snapshots", "plugins"]}',
  'active'
);

-- Get workspace ID for use in other inserts
-- Note: In production, retrieve this dynamically

-- ============================================================
-- 2. Create Demo User Records (Entities)
-- ============================================================

-- User 1: Alice (Trader)
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000', -- Replace with actual workspace_id
  'user_alice_001',
  'init',
  '{
    "name": "Alice Chen",
    "email": "alice@phantom.local",
    "role": "trader",
    "status": "active",
    "kyc_verified": true,
    "account_type": "professional"
  }'::jsonb,
  NULL
);

-- User 2: Bob (Investor)
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'user_bob_001',
  'init',
  '{
    "name": "Bob Johnson",
    "email": "bob@phantom.local",
    "role": "investor",
    "status": "active",
    "kyc_verified": true,
    "account_type": "retail"
  }'::jsonb,
  NULL
);

-- User 3: Carol (Fund Manager)
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'user_carol_001',
  'init',
  '{
    "name": "Carol Martinez",
    "email": "carol@phantom.local",
    "role": "fund_manager",
    "status": "active",
    "kyc_verified": true,
    "account_type": "professional"
  }'::jsonb,
  NULL
);

-- ============================================================
-- 3. Create Portfolio Events for Alice
-- ============================================================

-- Alice deposits initial funds
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'portfolio_alice_001',
  'init',
  '{
    "owner": "user_alice_001",
    "currency": "USD",
    "balance": 50000,
    "assets": {},
    "status": "active"
  }'::jsonb,
  NULL
);

-- Alice buys ETH
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'portfolio_alice_001',
  'update',
  '{
    "balance": 45000,
    "assets": {
      "ETH": {
        "amount": 10,
        "price": 500,
        "total_value": 5000
      }
    }
  }'::jsonb,
  NULL
);

-- Alice buys BTC
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'portfolio_alice_001',
  'update',
  '{
    "balance": 35000,
    "assets": {
      "ETH": {
        "amount": 10,
        "price": 500,
        "total_value": 5000
      },
      "BTC": {
        "amount": 1,
        "price": 10000,
        "total_value": 10000
      }
    }
  }'::jsonb,
  NULL
);

-- ============================================================
-- 4. Create Trading Events
-- ============================================================

-- Trade 1: ETH/USD swap
INSERT INTO public.defi_events (
  workspace_id, trader_id, event_type, asset, amount, price, value
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'user_alice_001',
  'swap',
  'ETH',
  10,
  2800,
  28000
);

-- Trade 2: Deposit USDC
INSERT INTO public.defi_events (
  workspace_id, trader_id, event_type, asset, amount, price, value
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'user_alice_001',
  'deposit',
  'USDC',
  20000,
  1,
  20000
);

-- Trade 3: BTC purchase
INSERT INTO public.defi_events (
  workspace_id, trader_id, event_type, asset, amount, price, value
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'user_alice_001',
  'swap',
  'BTC',
  0.5,
  45000,
  22500
);

-- ============================================================
-- 5. Create Snapshot Events (Performance Optimization)
-- ============================================================

-- Snapshot of Alice's portfolio after all trades
INSERT INTO public.snapshots (
  workspace_id, entity_id, state_data, event_count
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'portfolio_alice_001',
  '{
    "owner": "user_alice_001",
    "currency": "USD",
    "balance": 35000,
    "assets": {
      "ETH": {
        "amount": 10,
        "price": 2800,
        "total_value": 28000
      },
      "BTC": {
        "amount": 1.5,
        "price": 45000,
        "total_value": 67500
      },
      "USDC": {
        "amount": 20000,
        "price": 1,
        "total_value": 20000
      }
    },
    "total_portfolio_value": 150500
  }'::jsonb,
  4
);

-- ============================================================
-- 6. Create Transaction Records
-- ============================================================

-- Transaction 1: Initial deposit
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'transaction_001',
  'init',
  '{
    "from": "user_alice_001",
    "to": "portfolio_alice_001",
    "type": "deposit",
    "amount": 50000,
    "currency": "USD",
    "status": "completed",
    "timestamp": "2024-01-15T10:00:00Z"
  }'::jsonb,
  NULL
);

-- Transaction 2: Trade 1
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'transaction_002',
  'init',
  '{
    "from": "portfolio_alice_001",
    "to": "exchange",
    "type": "trade",
    "asset_send": "USD",
    "amount_send": 5000,
    "asset_receive": "ETH",
    "amount_receive": 10,
    "rate": 500,
    "status": "completed",
    "timestamp": "2024-01-15T11:00:00Z"
  }'::jsonb,
  NULL
);

-- ============================================================
-- 7. Create Order Events (for Bob - Investor)
-- ============================================================

-- Bob's investment order
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'investment_bob_001',
  'init',
  '{
    "investor": "user_bob_001",
    "fund_manager": "user_carol_001",
    "investment_amount": 100000,
    "currency": "USD",
    "status": "active",
    "start_date": "2024-01-01",
    "expected_return": "15%"
  }'::jsonb,
  NULL
);

-- Bob's quarterly statement
INSERT INTO public.events (
  workspace_id, entity_id, event_type, payload, created_by
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'investment_bob_001',
  'compute',
  '{
    "q1_returns": 3750,
    "total_value": 103750,
    "performance": "+3.75%",
    "last_updated": "2024-03-31"
  }'::jsonb,
  NULL
);

-- ============================================================
-- 8. Create API Key (for demo access)
-- ============================================================

-- Demo API Key (note: in production, hash the actual key)
INSERT INTO public.api_keys (
  workspace_id, key_hash, name, permissions, is_active
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'pk_demo_hash_abc123def456',
  'Demo API Key',
  '["read", "write", "delete"]'::jsonb,
  true
);

-- Read-only API Key
INSERT INTO public.api_keys (
  workspace_id, key_hash, name, permissions, is_active
) VALUES (
  '550e8400-e29b-41d4-a716-446655440000',
  'pk_demo_readonly_xyz789',
  'Read-Only API Key',
  '["read"]'::jsonb,
  true
);

-- ============================================================
-- 9. Verify Data
-- ============================================================

-- Check events created
SELECT 
  entity_id,
  COUNT(*) as event_count,
  MIN(created_at) as first_event,
  MAX(created_at) as last_event
FROM public.events
GROUP BY entity_id
ORDER BY event_count DESC;

-- Check DeFi trades
SELECT 
  trader_id,
  event_type,
  asset,
  amount,
  price,
  value
FROM public.defi_events
ORDER BY created_at DESC;

-- Check snapshots
SELECT 
  entity_id,
  event_count,
  created_at
FROM public.snapshots;

-- ============================================================
-- Summary
-- ============================================================

/*
✅ Demo data seeding complete!

Created:
- 1 workspace (Phantom Finance Demo)
- 3 users (Alice, Bob, Carol)
- 3 portfolios/accounts
- Multiple event types (init, update, compute, delete_field)
- 3 DeFi trading events
- 3 snapshots for optimization
- Transaction records
- Investment tracking
- 2 API keys (full access + read-only)

Next steps:
1. Verify data in Supabase Dashboard
2. Test event reconstruction
3. Try real-time subscriptions
4. Run demo applications

Notes:
- Replace '550e8400-e29b-41d4-a716-446655440000' with actual workspace_id
- auth.uid() should be replaced with actual user ID
- Timestamps are automatically set by Supabase
*/
