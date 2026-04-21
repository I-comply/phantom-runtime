import { createClient } from '@supabase/supabase-js'

/**
 * Phantom Runtime - Supabase Integration Demo
 * 
 * This demo shows:
 * 1. Authentication setup
 * 2. Creating a workspace
 * 3. Inserting events
 * 4. Reconstructing state
 * 5. Real-time subscriptions
 * 6. DeFi event tracking
 */

// Initialize Supabase client
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY
const supabase = createClient(supabaseUrl, supabaseAnonKey)

// ============================================================
// 1. Authentication Demo
// ============================================================

/**
 * Sign up a new user
 */
export async function demoSignUp(email: string, password: string) {
  console.log('📝 Signing up user:', email)
  
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: {
        display_name: email.split('@')[0],
      },
    },
  })

  if (error) {
    console.error('❌ Signup error:', error.message)
    return null
  }

  console.log('✅ User created:', data.user?.email)
  return data.user
}

/**
 * Sign in an existing user
 */
export async function demoSignIn(email: string, password: string) {
  console.log('🔐 Signing in user:', email)

  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })

  if (error) {
    console.error('❌ Sign-in error:', error.message)
    return null
  }

  console.log('✅ Signed in:', data.user?.email)
  return data.user
}

/**
 * Get current user
 */
export async function demoGetCurrentUser() {
  const { data, error } = await supabase.auth.getUser()

  if (error) {
    console.error('❌ Error getting user:', error.message)
    return null
  }

  console.log('👤 Current user:', data.user?.email)
  return data.user
}

// ============================================================
// 2. Workspace Management Demo
// ============================================================

/**
 * Create a new workspace
 */
export async function demoCreateWorkspace(name: string, description: string) {
  console.log('🏢 Creating workspace:', name)

  const { data, error } = await supabase
    .rpc('create_workspace', {
      p_name: name,
      p_description: description,
    })

  if (error) {
    console.error('❌ Error creating workspace:', error.message)
    return null
  }

  console.log('✅ Workspace created, ID:', data)
  return data
}

/**
 * Get user's workspaces
 */
export async function demoGetWorkspaces() {
  console.log('📋 Fetching workspaces...')

  const { data, error } = await supabase
    .from('workspaces')
    .select('*')
    .order('created_at', { ascending: false })

  if (error) {
    console.error('❌ Error fetching workspaces:', error.message)
    return null
  }

  console.log('✅ Found workspaces:', data.length)
  return data
}

/**
 * Get workspace stats
 */
export async function demoGetWorkspaceStats(workspaceId: string) {
  console.log('📊 Getting workspace stats...')

  const { data, error } = await supabase
    .rpc('get_workspace_stats', {
      p_workspace_id: workspaceId,
    })

  if (error) {
    console.error('❌ Error getting stats:', error.message)
    return null
  }

  console.log('✅ Workspace stats:', data)
  return data
}

// ============================================================
// 3. Event Creation Demo
// ============================================================

/**
 * Create an event
 */
export async function demoCreateEvent(
  workspaceId: string,
  entityId: string,
  eventType: string,
  payload: Record<string, any>
) {
  console.log('📝 Creating event:', { entityId, eventType })

  const { data, error } = await supabase
    .from('events')
    .insert([
      {
        workspace_id: workspaceId,
        entity_id: entityId,
        event_type: eventType,
        payload,
      },
    ])
    .select()

  if (error) {
    console.error('❌ Error creating event:', error.message)
    return null
  }

  console.log('✅ Event created:', data)
  return data
}

/**
 * Get events for an entity
 */
export async function demoGetEntityEvents(
  workspaceId: string,
  entityId: string
) {
  console.log('📖 Fetching events for:', entityId)

  const { data, error } = await supabase
    .rpc('get_entity_events', {
      p_entity_id: entityId,
      p_workspace_id: workspaceId,
      p_limit: 100,
    })

  if (error) {
    console.error('❌ Error fetching events:', error.message)
    return null
  }

  console.log('✅ Found events:', data.length)
  return data
}

/**
 * Get event count
 */
export async function demoGetEventCount(
  workspaceId: string,
  entityId: string
) {
  console.log('🔢 Getting event count...')

  const { data, error } = await supabase
    .rpc('get_event_count', {
      p_entity_id: entityId,
      p_workspace_id: workspaceId,
    })

  if (error) {
    console.error('❌ Error getting count:', error.message)
    return null
  }

  console.log('✅ Event count:', data)
  return data
}

// ============================================================
// 4. State Reconstruction Demo
// ============================================================

/**
 * Reconstruct entity state from events
 */
export async function demoReconstructState(events: any[]) {
  console.log('🔨 Reconstructing state from', events.length, 'events')

  let state: Record<string, any> = {}

  for (const event of events) {
    switch (event.event_type) {
      case 'init':
        state = event.payload
        break

      case 'update':
        state = { ...state, ...event.payload }
        break

      case 'compute':
        // Apply computed values
        Object.entries(event.payload).forEach(([key, value]) => {
          state[key] = value
        })
        break

      case 'delete_field':
        event.payload.fields?.forEach((field: string) => {
          delete state[field]
        })
        break

      case 'reset':
        state = {}
        break
    }
  }

  console.log('✅ State reconstructed:', state)
  return state
}

// ============================================================
// 5. Real-time Subscription Demo
// ============================================================

/**
 * Subscribe to new events in real-time
 */
export function demoSubscribeToEvents(workspaceId: string) {
  console.log('🔔 Subscribing to real-time events...')

  const subscription = supabase
    .from(`events:workspace_id=eq.${workspaceId}`)
    .on('INSERT', (payload) => {
      console.log('📨 New event received:', payload.new)
    })
    .on('UPDATE', (payload) => {
      console.log('🔄 Event updated:', payload.new)
    })
    .subscribe()

  console.log('✅ Subscribed to events')
  return subscription
}

/**
 * Subscribe to workspace updates
 */
export function demoSubscribeToWorkspace(workspaceId: string) {
  console.log('🔔 Subscribing to workspace changes...')

  const subscription = supabase
    .from(`workspaces:id=eq.${workspaceId}`)
    .on('UPDATE', (payload) => {
      console.log('🔄 Workspace updated:', payload.new)
    })
    .subscribe()

  return subscription
}

// ============================================================
// 6. DeFi Demo
// ============================================================

/**
 * Create DeFi event (trading)
 */
export async function demoCreateDeFiEvent(
  workspaceId: string,
  traderId: string,
  eventType: 'deposit' | 'withdraw' | 'swap' | 'trade',
  asset: string,
  amount: number,
  price: number
) {
  console.log('💰 Creating DeFi event:', { eventType, asset, amount })

  const { data, error } = await supabase
    .from('defi_events')
    .insert([
      {
        workspace_id: workspaceId,
        trader_id: traderId,
        event_type: eventType,
        asset,
        amount,
        price,
        value: amount * price,
      },
    ])
    .select()

  if (error) {
    console.error('❌ Error creating DeFi event:', error.message)
    return null
  }

  console.log('✅ DeFi event created:', data)
  return data
}

/**
 * Get trader portfolio
 */
export async function demoGetTraderPortfolio(
  workspaceId: string,
  traderId: string
) {
  console.log('💼 Fetching trader portfolio...')

  const { data: events, error } = await supabase
    .from('defi_events')
    .select('*')
    .eq('workspace_id', workspaceId)
    .eq('trader_id', traderId)
    .order('created_at', { ascending: true })

  if (error) {
    console.error('❌ Error fetching portfolio:', error.message)
    return null
  }

  // Calculate portfolio from events
  const portfolio: Record<string, number> = {}
  let totalValue = 0

  events.forEach((event: any) => {
    if (!portfolio[event.asset]) {
      portfolio[event.asset] = 0
    }

    if (event.event_type === 'deposit') {
      portfolio[event.asset] += event.amount
    } else if (event.event_type === 'withdraw') {
      portfolio[event.asset] -= event.amount
    }

    totalValue += event.value || 0
  })

  console.log('✅ Portfolio:', { assets: portfolio, totalValue })
  return { portfolio, totalValue, events }
}

// ============================================================
// 7. Snapshot Demo (Performance Optimization)
// ============================================================

/**
 * Create a snapshot of current state
 */
export async function demoCreateSnapshot(
  workspaceId: string,
  entityId: string,
  state: Record<string, any>
) {
  console.log('📸 Creating snapshot for:', entityId)

  const { data, error } = await supabase
    .from('snapshots')
    .insert([
      {
        workspace_id: workspaceId,
        entity_id: entityId,
        state_data: state,
        event_count: 0, // Will be filled by trigger
      },
    ])
    .select()

  if (error) {
    console.error('❌ Error creating snapshot:', error.message)
    return null
  }

  console.log('✅ Snapshot created:', data)
  return data
}

/**
 * Get latest snapshot
 */
export async function demoGetLatestSnapshot(
  workspaceId: string,
  entityId: string
) {
  console.log('📸 Getting latest snapshot...')

  const { data, error } = await supabase
    .from('snapshots')
    .select('*')
    .eq('workspace_id', workspaceId)
    .eq('entity_id', entityId)
    .order('created_at', { ascending: false })
    .limit(1)
    .single()

  if (error) {
    console.error('❌ Error getting snapshot:', error.message)
    return null
  }

  console.log('✅ Snapshot retrieved:', data)
  return data
}

// ============================================================
// 8. Complete Demo Flow
// ============================================================

/**
 * Run complete demo
 */
export async function runCompleteDemo() {
  console.log('🚀 Starting Phantom Runtime Supabase Demo...\n')

  try {
    // 1. Sign up
    const user = await demoSignUp('demo@phantom.local', 'Demo123!@#')
    if (!user) return

    // 2. Create workspace
    const workspaceId = await demoCreateWorkspace(
      'My Trading Workspace',
      'Demo workspace for Phantom Runtime'
    )
    if (!workspaceId) return

    // 3. Create initial event
    await demoCreateEvent(
      workspaceId,
      'user_001',
      'init',
      { name: 'Alice', balance: 1000 }
    )

    // 4. Get events
    const events = await demoGetEntityEvents(workspaceId, 'user_001')
    if (!events) return

    // 5. Reconstruct state
    await demoReconstructState(events)

    // 6. Subscribe to real-time
    const subscription = demoSubscribeToEvents(workspaceId)

    // 7. Create DeFi events
    await demoCreateDeFiEvent(
      workspaceId,
      'trader_bob',
      'deposit',
      'ETH',
      10,
      3500
    )
    await demoCreateDeFiEvent(
      workspaceId,
      'trader_bob',
      'swap',
      'USDC',
      35000,
      1
    )

    // 8. Get portfolio
    await demoGetTraderPortfolio(workspaceId, 'trader_bob')

    // 9. Create snapshot
    const state = { name: 'Alice', balance: 1000 }
    await demoCreateSnapshot(workspaceId, 'user_001', state)

    // 10. Get stats
    await demoGetWorkspaceStats(workspaceId)

    console.log('\n✅ Demo completed successfully!')
    console.log('📝 Check browser console for detailed output')

    return subscription
  } catch (error) {
    console.error('❌ Demo error:', error)
  }
}
