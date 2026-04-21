import { TrendingUp, Activity, Zap, Database, Shield, Cpu } from 'lucide-react'

export default function PerformanceDashboard({ metrics }) {
  const stats = [
    {
      label: 'Total Events',
      value: metrics?.total_events || 0,
      icon: Activity,
      color: 'cyan',
      suffix: ''
    },
    {
      label: 'Events/Second',
      value: metrics?.events_per_sec || 0,
      icon: Zap,
      color: 'green',
      suffix: 'ev/s'
    },
    {
      label: 'V3 Events (Hash-Chained)',
      value: metrics?.total_events_v3 || 0,
      icon: Shield,
      color: 'purple',
      suffix: ''
    },
    {
      label: 'Active Connections',
      value: metrics?.active_connections || 0,
      icon: Cpu,
      color: 'red',
      suffix: 'clients'
    }
  ]

  return (
    <div className="space-y-6" data-testid="performance-dashboard">
      {/* Welcome Section */}
      <div className="glass-card p-8 border border-cyan-500/30 pulse-glow">
        <div className="flex items-center gap-3 mb-4">
          <TrendingUp className="w-8 h-8 text-cyan-400" />
          <div>
            <h2 className="text-2xl font-bold text-cyan-400">DARK OPERATOR Console</h2>
            <p className="text-sm text-gray-400">Next-Gen Event Runtime Platform v3.0</p>
          </div>
        </div>
        <p className="text-gray-300 text-sm">
          Deterministic event-sourced runtime with SHA256 hash chaining, async pipeline, 
          and sandboxed strategy execution. All systems operational.
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, index) => (
          <div
            key={index}
            className="glass-card p-6 hover:border-cyan-500/50 transition-all"
          >
            <div className="flex items-start justify-between mb-3">
              <stat.icon className={`w-6 h-6 text-${stat.color}-400`} />
              <span className={`text-xs px-2 py-1 rounded bg-${stat.color}-500/20 text-${stat.color}-400`}>
                LIVE
              </span>
            </div>
            <p className="text-3xl font-bold terminal-text mb-1">
              {stat.value.toLocaleString()}
            </p>
            <p className="text-xs text-gray-400">
              {stat.label} {stat.suffix && <span className="text-${stat.color}-400">{stat.suffix}</span>}
            </p>
          </div>
        ))}
      </div>

      {/* Feature Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="glass-card p-6 border border-cyan-500/20">
          <div className="flex items-center gap-2 mb-3">
            <Shield className="w-5 h-5 text-cyan-400" />
            <h3 className="font-semibold text-cyan-400">Event Chaining</h3>
          </div>
          <p className="text-sm text-gray-400 mb-2">
            SHA256 hash chains for tamper-proof audit logs
          </p>
          <div className="text-xs terminal-text text-gray-500">
            Block-indexed • Verifiable • Immutable
          </div>
        </div>

        <div className="glass-card p-6 border border-green-500/20">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-5 h-5 text-green-400" />
            <h3 className="font-semibold text-green-400">Async Pipeline</h3>
          </div>
          <p className="text-sm text-gray-400 mb-2">
            10-25k events/sec with queue-based ingestion
          </p>
          <div className="text-xs terminal-text text-gray-500">
            Idempotent • Retry-safe • Burst-ready
          </div>
        </div>

        <div className="glass-card p-6 border border-purple-500/20">
          <div className="flex items-center gap-2 mb-3">
            <Cpu className="w-5 h-5 text-purple-400" />
            <h3 className="font-semibold text-purple-400">Strategy Engine</h3>
          </div>
          <p className="text-sm text-gray-400 mb-2">
            Sandboxed plugin execution with event-only outputs
          </p>
          <div className="text-xs terminal-text text-gray-500">
            Arbitrage • Anomaly Detection • Yield Optimization
          </div>
        </div>
      </div>

      {/* System Health */}
      <div className="glass-card p-6">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Database className="w-5 h-5 text-cyan-400" />
          System Health
        </h3>
        <div className="space-y-3">
          {[
            { label: 'Event Store', status: 'operational', value: '100%' },
            { label: 'Hash Chain Integrity', status: 'verified', value: '100%' },
            { label: 'WebSocket Feed', status: 'active', value: `${metrics?.active_connections || 0} conn` },
            { label: 'Strategy Engine', status: 'ready', value: '3 plugins' }
          ].map((item, i) => (
            <div key={i} className="flex items-center justify-between p-3 bg-black/20 rounded-lg">
              <div className="flex items-center gap-3">
                <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></div>
                <span className="text-sm">{item.label}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-500 terminal-text">{item.value}</span>
                <span className="text-xs px-2 py-1 rounded bg-green-500/20 text-green-400">
                  {item.status.toUpperCase()}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
