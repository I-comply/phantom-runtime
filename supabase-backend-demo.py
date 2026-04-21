"""
Phantom Runtime - Supabase Integration Demo (Python/FastAPI)

This demo shows backend integration with Supabase:
1. Authenticate with Supabase
2. Create and query events
3. Implement event sourcing
4. Real-time webhooks
5. State reconstruction
"""

from typing import Any, Dict, List, Optional
import os
from datetime import datetime, timedelta
import json
from supabase import create_client, Client
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv('.env.supabase')

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ============================================================
# Data Models
# ============================================================

class Event(BaseModel):
    entity_id: str
    event_type: str
    payload: Dict[str, Any]
    workspace_id: str

class Workspace(BaseModel):
    name: str
    description: Optional[str] = None
    settings: Dict[str, Any] = {"tier": "free"}

class StateSnapshot(BaseModel):
    entity_id: str
    workspace_id: str
    state_data: Dict[str, Any]

# ============================================================
# Authentication & Setup
# ============================================================

async def demo_authenticate_service_role():
    """Authenticate as service role (backend operations)"""
    print("🔐 Authenticating as service role...")
    
    # Service role already authenticated via client initialization
    print("✅ Service role authenticated")
    return True

async def demo_get_workspace_by_owner(owner_email: str):
    """Get workspace owned by user"""
    print(f"🔍 Finding workspace for {owner_email}...")
    
    response = supabase.table('workspaces').select('*').execute()
    workspaces = response.data
    
    print(f"✅ Found {len(workspaces)} workspaces")
    return workspaces

# ============================================================
# Event Creation & Management
# ============================================================

async def demo_create_event(
    workspace_id: str,
    entity_id: str,
    event_type: str,
    payload: Dict[str, Any]
) -> Optional[Dict]:
    """Create an event"""
    print(f"📝 Creating event: {event_type} for {entity_id}")
    
    response = supabase.table('events').insert([
        {
            'workspace_id': workspace_id,
            'entity_id': entity_id,
            'event_type': event_type,
            'payload': payload,
            'created_at': datetime.utcnow().isoformat()
        }
    ]).execute()
    
    if response.data:
        print(f"✅ Event created: {response.data[0]['id']}")
        return response.data[0]
    else:
        print("❌ Error creating event")
        return None

async def demo_get_entity_events(
    workspace_id: str,
    entity_id: str,
    limit: int = 100
) -> List[Dict]:
    """Get all events for an entity"""
    print(f"📖 Fetching events for {entity_id}...")
    
    response = supabase.rpc(
        'get_entity_events',
        {
            'p_entity_id': entity_id,
            'p_workspace_id': workspace_id,
            'p_limit': limit
        }
    ).execute()
    
    events = response.data or []
    print(f"✅ Found {len(events)} events")
    return events

async def demo_get_recent_events(
    workspace_id: str,
    hours: int = 24
) -> List[Dict]:
    """Get recent events"""
    print(f"📋 Fetching events from last {hours} hours...")
    
    cutoff_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    
    response = supabase.table('events') \
        .select('*') \
        .eq('workspace_id', workspace_id) \
        .gte('created_at', cutoff_time) \
        .order('created_at', desc=True) \
        .execute()
    
    events = response.data or []
    print(f"✅ Found {len(events)} recent events")
    return events

# ============================================================
# State Reconstruction
# ============================================================

def demo_reconstruct_state(events: List[Dict]) -> Dict[str, Any]:
    """Reconstruct state from event log"""
    print(f"🔨 Reconstructing state from {len(events)} events...")
    
    state = {}
    
    # Events should be ordered by created_at (oldest first)
    for event in sorted(events, key=lambda e: e.get('created_at', '')):
        event_type = event.get('event_type')
        payload = event.get('payload', {})
        
        if event_type == 'init':
            # Initialize state
            state = payload.copy()
            
        elif event_type == 'update':
            # Merge updates
            state.update(payload)
            
        elif event_type == 'compute':
            # Apply computed values
            for key, value in payload.items():
                state[key] = value
                
        elif event_type == 'delete_field':
            # Remove fields
            for field in payload.get('fields', []):
                state.pop(field, None)
                
        elif event_type == 'reset':
            # Clear state
            state = {}
    
    print(f"✅ State reconstructed: {json.dumps(state, indent=2)}")
    return state

async def demo_get_entity_state(
    workspace_id: str,
    entity_id: str
) -> Dict[str, Any]:
    """Get current entity state"""
    print(f"📊 Getting state for {entity_id}...")
    
    # Get events
    events = await demo_get_entity_events(workspace_id, entity_id)
    
    # Reconstruct state
    state = demo_reconstruct_state(events)
    
    # Get metadata
    event_count = len(events)
    
    result = {
        'entity_id': entity_id,
        'state': state,
        'event_count': event_count,
        'runtime_status': 'active'
    }
    
    print(f"✅ State retrieved")
    return result

# ============================================================
# Snapshot Management
# ============================================================

async def demo_create_snapshot(
    workspace_id: str,
    entity_id: str,
    state: Dict[str, Any]
) -> Optional[Dict]:
    """Create state snapshot"""
    print(f"📸 Creating snapshot for {entity_id}...")
    
    response = supabase.table('snapshots').insert([
        {
            'workspace_id': workspace_id,
            'entity_id': entity_id,
            'state_data': state,
            'created_at': datetime.utcnow().isoformat()
        }
    ]).execute()
    
    if response.data:
        print(f"✅ Snapshot created")
        return response.data[0]
    else:
        print("❌ Error creating snapshot")
        return None

async def demo_get_latest_snapshot(
    workspace_id: str,
    entity_id: str
) -> Optional[Dict]:
    """Get latest snapshot"""
    print(f"📸 Getting latest snapshot for {entity_id}...")
    
    response = supabase.table('snapshots') \
        .select('*') \
        .eq('workspace_id', workspace_id) \
        .eq('entity_id', entity_id) \
        .order('created_at', desc=True) \
        .limit(1) \
        .execute()
    
    if response.data:
        print(f"✅ Snapshot found")
        return response.data[0]
    else:
        print("⚠️  No snapshot found")
        return None

async def demo_fast_state_recovery(
    workspace_id: str,
    entity_id: str
) -> Dict[str, Any]:
    """
    Fast state recovery using snapshots.
    Get snapshot + recent events, reconstruct from snapshot point.
    """
    print(f"⚡ Fast recovery for {entity_id}...")
    
    # Get latest snapshot
    snapshot = await demo_get_latest_snapshot(workspace_id, entity_id)
    
    if snapshot:
        state = snapshot['state_data']
        snapshot_time = snapshot['created_at']
        print(f"  Using snapshot from {snapshot_time}")
        
        # Get events since snapshot
        response = supabase.table('events') \
            .select('*') \
            .eq('workspace_id', workspace_id) \
            .eq('entity_id', entity_id) \
            .gt('created_at', snapshot_time) \
            .order('created_at', asc=True) \
            .execute()
        
        recent_events = response.data or []
        print(f"  Replaying {len(recent_events)} recent events")
        
        # Replay recent events
        state = demo_reconstruct_state([{'event_type': 'init', 'payload': state}] + recent_events)
    else:
        # No snapshot, reconstruct from beginning
        events = await demo_get_entity_events(workspace_id, entity_id)
        state = demo_reconstruct_state(events)
    
    print(f"✅ Fast recovery complete")
    return state

# ============================================================
# DeFi Demo
# ============================================================

async def demo_create_defi_event(
    workspace_id: str,
    trader_id: str,
    event_type: str,  # deposit, withdraw, swap, trade
    asset: str,
    amount: float,
    price: float
) -> Optional[Dict]:
    """Create DeFi event"""
    print(f"💰 Creating DeFi event: {event_type} {amount} {asset}")
    
    response = supabase.table('defi_events').insert([
        {
            'workspace_id': workspace_id,
            'trader_id': trader_id,
            'event_type': event_type,
            'asset': asset,
            'amount': amount,
            'price': price,
            'value': amount * price,
            'created_at': datetime.utcnow().isoformat()
        }
    ]).execute()
    
    if response.data:
        print(f"✅ DeFi event created")
        return response.data[0]
    else:
        print("❌ Error creating DeFi event")
        return None

async def demo_get_trader_portfolio(
    workspace_id: str,
    trader_id: str
) -> Dict[str, Any]:
    """Get trader portfolio from DeFi events"""
    print(f"💼 Fetching trader portfolio...")
    
    response = supabase.table('defi_events') \
        .select('*') \
        .eq('workspace_id', workspace_id) \
        .eq('trader_id', trader_id) \
        .order('created_at', asc=True) \
        .execute()
    
    events = response.data or []
    
    # Calculate portfolio
    portfolio = {}
    total_value = 0
    
    for event in events:
        asset = event.get('asset')
        amount = event.get('amount', 0)
        value = event.get('value', 0)
        event_type = event.get('event_type')
        
        if asset not in portfolio:
            portfolio[asset] = 0
        
        if event_type == 'deposit':
            portfolio[asset] += amount
        elif event_type == 'withdraw':
            portfolio[asset] -= amount
        
        total_value += value
    
    result = {
        'trader_id': trader_id,
        'portfolio': portfolio,
        'total_value': total_value,
        'event_count': len(events)
    }
    
    print(f"✅ Portfolio: {portfolio}")
    return result

# ============================================================
# Analytics
# ============================================================

async def demo_get_workspace_stats(workspace_id: str) -> Dict[str, Any]:
    """Get workspace statistics"""
    print(f"📊 Getting workspace stats...")
    
    response = supabase.rpc(
        'get_workspace_stats',
        {'p_workspace_id': workspace_id}
    ).execute()
    
    if response.data:
        stats = response.data[0] if isinstance(response.data, list) else response.data
        print(f"✅ Stats: {stats}")
        return stats
    else:
        print("❌ Error getting stats")
        return {}

async def demo_get_event_metrics(workspace_id: str) -> Dict[str, Any]:
    """Get event metrics"""
    print(f"📈 Getting event metrics...")
    
    response = supabase.table('events') \
        .select('event_type, count()') \
        .eq('workspace_id', workspace_id) \
        .execute()
    
    # Group by event type
    metrics = {}
    for item in response.data or []:
        event_type = item.get('event_type')
        if event_type:
            metrics[event_type] = metrics.get(event_type, 0) + 1
    
    print(f"✅ Event metrics: {metrics}")
    return metrics

# ============================================================
# Complete Demo Flow
# ============================================================

async def run_backend_demo():
    """Run complete backend demo"""
    print("🚀 Starting Phantom Runtime Backend Demo (Supabase)\n")
    
    try:
        # 1. Authenticate
        await demo_authenticate_service_role()
        
        # Use a sample workspace ID (you'd get this from actual workspace)
        workspace_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # 2. Create events
        await demo_create_event(
            workspace_id,
            'user_123',
            'init',
            {'name': 'Alice', 'balance': 1000, 'status': 'active'}
        )
        
        await demo_create_event(
            workspace_id,
            'user_123',
            'update',
            {'balance': 1500}
        )
        
        # 3. Get events
        events = await demo_get_entity_events(workspace_id, 'user_123')
        
        # 4. Reconstruct state
        state = demo_reconstruct_state(events)
        
        # 5. Create snapshot
        await demo_create_snapshot(workspace_id, 'user_123', state)
        
        # 6. Fast recovery
        recovered_state = await demo_fast_state_recovery(workspace_id, 'user_123')
        
        # 7. DeFi demo
        await demo_create_defi_event(
            workspace_id,
            'trader_bob',
            'deposit',
            'ETH',
            10,
            3500
        )
        await demo_create_defi_event(
            workspace_id,
            'trader_bob',
            'swap',
            'USDC',
            35000,
            1
        )
        
        # 8. Get portfolio
        await demo_get_trader_portfolio(workspace_id, 'trader_bob')
        
        # 9. Get stats
        await demo_get_workspace_stats(workspace_id)
        
        # 10. Get metrics
        await demo_get_event_metrics(workspace_id)
        
        print("\n✅ Backend demo completed successfully!")
        
    except Exception as e:
        print(f"❌ Demo error: {e}")
        raise

# Run demo
if __name__ == '__main__':
    import asyncio
    asyncio.run(run_backend_demo())
