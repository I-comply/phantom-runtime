import { useState, useEffect } from 'react'
import { Eye, RefreshCw } from 'lucide-react'
import axios from 'axios'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'https://phantom-runtime.preview.emergentagent.com'

export default function StateViewer({ entityId }) {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadState = async () => {
    if (!entityId) return
    setLoading(true)
    setError('')
    try {
      const res = await axios.get(`${BACKEND_URL}/api/state/${entityId}`)
      setState(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load state')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadState()
  }, [entityId])

  return (
    <div className="glass-card p-6 h-[calc(100vh-250px)]" data-testid="state-viewer">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Eye className="w-5 h-5 text-green-400" />
          <h2 className="text-lg font-semibold text-green-400">State Viewer</h2>
        </div>
        <button
          onClick={loadState}
          disabled={!entityId || loading}
          className="p-2 rounded-lg bg-gray-800/50 hover:bg-gray-700/50 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {!entityId && (
        <div className="flex items-center justify-center h-[calc(100%-60px)] text-gray-500">
          <p className="text-sm">Select an entity to view state</p>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          {error}
        </div>
      )}

      {state && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="glass-card p-3">
              <p className="text-gray-500 text-xs mb-1">Events</p>
              <p className="text-xl font-bold text-cyan-400 terminal-text">{state.event_count}</p>
            </div>
            <div className="glass-card p-3">
              <p className="text-gray-500 text-xs mb-1">Snapshot</p>
              <p className="text-xl font-bold text-green-400 terminal-text">
                {state.snapshot_used ? `#${state.snapshot_number}` : 'None'}
              </p>
            </div>
          </div>

          <div className="glass-card p-4 overflow-auto max-h-[calc(100vh-450px)]">
            <pre className="text-xs terminal-text text-gray-300">
              {JSON.stringify(state.state, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
