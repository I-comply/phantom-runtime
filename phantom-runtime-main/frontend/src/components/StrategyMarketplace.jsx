import { useState, useEffect } from 'react'
import { Cpu, Play, Code, TrendingUp } from 'lucide-react'
import axios from 'axios'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'https://phantom-runtime.preview.emergentagent.com'

export default function StrategyMarketplace() {
  const [builtinStrategies, setBuiltinStrategies] = useState([])
  const [selectedStrategy, setSelectedStrategy] = useState(null)
  const [entityId, setEntityId] = useState('')
  const [executing, setExecuting] = useState(false)
  const [result, setResult] = useState(null)

  useEffect(() => {
    loadBuiltinStrategies()
  }, [])

  const loadBuiltinStrategies = async () => {
    try {
      const res = await axios.get(`${BACKEND_URL}/api/v3/strategies/builtins`)
      setBuiltinStrategies(res.data.strategies || [])
    } catch (err) {
      console.error('Failed to load strategies:', err)
    }
  }

  const executeStrategy = async () => {
    if (!selectedStrategy || !entityId) return
    setExecuting(true)
    setResult(null)
    try {
      // First create the strategy
      const createRes = await axios.post(`${BACKEND_URL}/api/v3/strategies`, {
        name: `${selectedStrategy}_${Date.now()}`,
        strategy_type: selectedStrategy
      })

      // Then execute it
      const execRes = await axios.post(
        `${BACKEND_URL}/api/v3/strategies/${createRes.data.id}/execute?entity_id=${entityId}&emit_events=true`
      )

      setResult(execRes.data)
    } catch (err) {
      setResult({ error: err.response?.data?.detail || err.message })
    } finally {
      setExecuting(false)
    }
  }

  return (
    <div className="space-y-6" data-testid="strategy-marketplace">
      <div className="glass-card p-6">
        <div className="flex items-center gap-3 mb-6">
          <Cpu className="w-6 h-6 text-purple-400" />
          <h2 className="text-2xl font-bold text-purple-400">Strategy Marketplace</h2>
        </div>

        {/* Strategy Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          {builtinStrategies.map((strategy) => (
            <div
              key={strategy}
              onClick={() => setSelectedStrategy(strategy)}
              className={`
                glass-card p-4 cursor-pointer transition-all
                ${
                  selectedStrategy === strategy
                    ? 'border-purple-500/50 glow-cyan'
                    : 'border-gray-700/50 hover:border-purple-500/30'
                }
              `}
            >
              <div className="flex items-center gap-2 mb-2">
                <div className={`w-3 h-3 rounded-full ${
                  selectedStrategy === strategy ? 'bg-purple-400' : 'bg-gray-600'
                }`}></div>
                <h3 className="font-semibold text-sm">{strategy}</h3>
              </div>
              <p className="text-xs text-gray-400">
                {strategy === 'arbitrage' && 'Detects price differences across events'}
                {strategy === 'anomaly_detector' && 'Flags unusual patterns in event stream'}
                {strategy === 'yield_optimizer' && 'Calculates optimal yield allocation'}
              </p>
            </div>
          ))}
        </div>

        {/* Execution Panel */}
        {selectedStrategy && (
          <div className="glass-card p-6 border border-purple-500/30">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Code className="w-5 h-5 text-purple-400" />
              Execute: {selectedStrategy}
            </h3>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-2">Entity ID</label>
                <input
                  type="text"
                  value={entityId}
                  onChange={(e) => setEntityId(e.target.value)}
                  placeholder="Enter entity ID"
                  className="w-full px-4 py-2 bg-black/30 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-purple-500"
                  data-testid="strategy-entity-input"
                />
              </div>

              <button
                onClick={executeStrategy}
                disabled={!entityId || executing}
                className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
                data-testid="execute-strategy-btn"
              >
                <Play className={`w-4 h-4 ${executing ? 'animate-spin' : ''}`} />
                {executing ? 'Executing...' : 'Execute Strategy'}
              </button>
            </div>

            {/* Result Display */}
            {result && (
              <div className="mt-6">
                <h4 className="text-sm font-semibold mb-2 text-green-400">Execution Result</h4>
                <pre className="bg-black/50 p-4 rounded-lg text-xs terminal-text overflow-auto max-h-64">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
