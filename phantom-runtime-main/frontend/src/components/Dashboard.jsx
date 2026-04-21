import { useState, useEffect } from 'react'
import { Activity, Database, Zap } from 'lucide-react'
import { stateAPI, eventsAPI } from '../api'

export default function Dashboard() {
  const [entities, setEntities] = useState([])
  const [selectedEntity, setSelectedEntity] = useState('')
  const [entityState, setEntityState] = useState(null)
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // New event form
  const [newEvent, setNewEvent] = useState({
    entity_id: '',
    event_type: 'init',
    payload: '{}'
  })

  useEffect(() => {
    loadEntities()
  }, [])

  const loadEntities = async () => {
    try {
      const res = await stateAPI.getAllEntities()
      setEntities(res.data)
    } catch (err) {
      console.error('Failed to load entities:', err)
    }
  }

  const loadEntityState = async (entityId) => {
    if (!entityId) return
    setLoading(true)
    setError('')
    try {
      const [stateRes, eventsRes] = await Promise.all([
        stateAPI.getEntityState(entityId),
        eventsAPI.getEntityEvents(entityId)
      ])
      setEntityState(stateRes.data)
      setEvents(eventsRes.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load entity')
      setEntityState(null)
      setEvents([])
    } finally {
      setLoading(false)
    }
  }

  const handleSelectEntity = (entityId) => {
    setSelectedEntity(entityId)
    loadEntityState(entityId)
  }

  const handleCreateEvent = async (e) => {
    e.preventDefault()
    setError('')
    try {
      const payload = JSON.parse(newEvent.payload)
      await eventsAPI.createEvent({
        entity_id: newEvent.entity_id,
        event_type: newEvent.event_type,
        payload
      })
      setNewEvent({ entity_id: '', event_type: 'init', payload: '{}' })
      await loadEntities()
      if (selectedEntity === newEvent.entity_id) {
        await loadEntityState(selectedEntity)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid JSON or request failed')
    }
  }

  const handleRunAgent = async () => {
    if (!selectedEntity) return
    setError('')
    try {
      await stateAPI.runAgent({
        entity_id: selectedEntity,
        operation: 'process'
      })
      await loadEntityState(selectedEntity)
    } catch (err) {
      setError(err.response?.data?.detail || 'Agent execution failed')
    }
  }

  return (
    <div className="min-h-screen p-6" style={{ background: 'var(--bg-primary)' }}>
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <Database className="w-8 h-8" style={{ color: 'var(--accent)' }} />
          <h1 className="text-3xl font-bold">PhantomOS Runtime Engine</h1>
        </div>

        {/* Error Display */}
        {error && (
          <div className="p-4 rounded-lg" style={{ background: '#991b1b20', border: '1px solid #dc2626' }}>
            <p style={{ color: '#fca5a5' }}>{error}</p>
          </div>
        )}

        {/* Create Event Form */}
        <div className="p-6 rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Zap className="w-5 h-5" style={{ color: 'var(--accent)' }} />
            Create Event
          </h2>
          <form onSubmit={handleCreateEvent} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <input
                data-testid="entity-id-input"
                type="text"
                placeholder="Entity ID"
                value={newEvent.entity_id}
                onChange={(e) => setNewEvent({ ...newEvent, entity_id: e.target.value })}
                required
                className="px-4 py-2 rounded-lg outline-none"
                style={{
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)'
                }}
              />
              <select
                data-testid="event-type-select"
                value={newEvent.event_type}
                onChange={(e) => setNewEvent({ ...newEvent, event_type: e.target.value })}
                className="px-4 py-2 rounded-lg outline-none"
                style={{
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)'
                }}
              >
                <option value="init">init</option>
                <option value="update">update</option>
                <option value="compute">compute</option>
                <option value="reset">reset</option>
              </select>
              <input
                data-testid="payload-input"
                type="text"
                placeholder='Payload JSON {"key": "value"}'
                value={newEvent.payload}
                onChange={(e) => setNewEvent({ ...newEvent, payload: e.target.value })}
                required
                className="px-4 py-2 rounded-lg outline-none"
                style={{
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)'
                }}
              />
            </div>
            <button
              data-testid="create-event-btn"
              type="submit"
              className="px-6 py-2 rounded-lg font-medium transition-all"
              style={{
                background: 'var(--accent)',
                color: 'white'
              }}
            >
              Append Event
            </button>
          </form>
        </div>

        {/* Entity Selection */}
        <div className="p-6 rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Activity className="w-5 h-5" style={{ color: 'var(--accent)' }} />
            Entity Runtime
          </h2>
          <div className="flex gap-4 items-center">
            <select
              data-testid="entity-select"
              value={selectedEntity}
              onChange={(e) => handleSelectEntity(e.target.value)}
              className="flex-1 px-4 py-2 rounded-lg outline-none"
              style={{
                background: 'var(--bg-secondary)',
                border: '1px solid var(--border)',
                color: 'var(--text-primary)'
              }}
            >
              <option value="">Select an entity...</option>
              {entities.map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
            <button
              data-testid="run-agent-btn"
              onClick={handleRunAgent}
              disabled={!selectedEntity}
              className="px-6 py-2 rounded-lg font-medium transition-all disabled:opacity-50"
              style={{
                background: 'var(--accent-light)',
                color: 'white'
              }}
            >
              Run Agent
            </button>
          </div>
        </div>

        {/* State & Events Display */}
        {loading && <div className="text-center py-8" style={{ color: 'var(--text-secondary)' }}>Loading...</div>}
        
        {entityState && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Reconstructed State */}
            <div className="p-6 rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
              <h3 className="text-lg font-semibold mb-3" style={{ color: 'var(--accent)' }}>Reconstructed State</h3>
              <div className="mb-2">
                <span style={{ color: 'var(--text-secondary)' }}>Event Count:</span>
                <span className="ml-2 font-mono">{entityState.event_count}</span>
              </div>
              <div className="mb-2">
                <span style={{ color: 'var(--text-secondary)' }}>Runtime Status:</span>
                <span className="ml-2 font-mono">{entityState.runtime_status}</span>
              </div>
              <pre
                data-testid="state-display"
                className="mt-4 p-4 rounded overflow-auto text-sm"
                style={{
                  background: 'var(--bg-secondary)',
                  color: 'var(--text-primary)',
                  maxHeight: '400px'
                }}
              >
                {JSON.stringify(entityState.state, null, 2)}
              </pre>
            </div>

            {/* Event Log */}
            <div className="p-6 rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
              <h3 className="text-lg font-semibold mb-3" style={{ color: 'var(--accent)' }}>Event Log</h3>
              <div className="space-y-2 overflow-auto" style={{ maxHeight: '500px' }}>
                {events.map((event) => (
                  <div
                    key={event.id}
                    className="p-3 rounded"
                    style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <span className="font-mono text-sm font-semibold" style={{ color: 'var(--accent-light)' }}>
                        {event.event_type}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                        #{event.id}
                      </span>
                    </div>
                    <pre className="text-xs overflow-auto" style={{ color: 'var(--text-secondary)' }}>
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                    <div className="text-xs mt-2" style={{ color: 'var(--text-secondary)' }}>
                      {new Date(event.created_at).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
