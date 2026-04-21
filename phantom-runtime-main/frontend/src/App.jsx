import { useState, useEffect, useRef } from 'react'
import { Activity, Zap, TrendingUp, Database, Shield, Cpu } from 'lucide-react'
import EventStream from './components/EventStream'
import StateViewer from './components/StateViewer'
import StrategyMarketplace from './components/StrategyMarketplace'
import PerformanceDashboard from './components/PerformanceDashboard'
import { useWebSocket } from './hooks/useWebSocket'
import './App.css'

function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [selectedEntity, setSelectedEntity] = useState('')
  const { events, metrics, isConnected } = useWebSocket()

  return (
    <div className="app-container">
      {/* Animated Grid Background */}
      <div className="grid-background"></div>

      {/* Main Content */}
      <div className="relative z-10">
        {/* Header */}
        <header className="header glass-card">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Database className="w-8 h-8 text-cyan-400" style={{ filter: 'drop-shadow(0 0 8px #00E5FF)' }} />
              <div>
                <h1 className="text-2xl font-bold bg-gradient-to-r from-cyan-400 to-green-400 bg-clip-text text-transparent">
                  Phantom Finance
                </h1>
                <p className="text-xs text-gray-400 terminal-text">v3.0 DARK_OPERATOR</p>
              </div>
            </div>

            <div className="flex items-center gap-6">
              {/* System Status */}
              <div className="flex items-center gap-2">
                <div className={`status-${isConnected ? 'online' : 'offline'}`}></div>
                <span className="text-sm text-gray-400">
                  {isConnected ? 'Live Feed Active' : 'Reconnecting...'}
                </span>
              </div>

              {/* Performance Metrics */}
              <div className="flex items-center gap-4 px-4 py-2 glass-card">
                <div className="flex items-center gap-2">
                  <Zap className="w-4 h-4 text-cyan-400" />
                  <span className="text-sm terminal-text">{metrics?.events_per_sec || 0} ev/s</span>
                </div>
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-green-400" />
                  <span className="text-sm terminal-text">{metrics?.total_events || 0} total</span>
                </div>
              </div>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="flex gap-2 mt-4">
            {[
              { id: 'dashboard', icon: TrendingUp, label: 'Dashboard' },
              { id: 'events', icon: Activity, label: 'Event Stream' },
              { id: 'strategies', icon: Cpu, label: 'Strategies' },
              { id: 'security', icon: Shield, label: 'Security' }
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  flex items-center gap-2 px-4 py-2 rounded-lg transition-all
                  ${activeTab === tab.id
                    ? 'bg-cyan-500/20 border border-cyan-500/50 text-cyan-400'
                    : 'bg-gray-800/30 border border-gray-700/30 text-gray-400 hover:border-cyan-500/30'
                  }
                `}
                data-testid={`tab-${tab.id}`}
              >
                <tab.icon className="w-4 h-4" />
                <span className="text-sm font-medium">{tab.label}</span>
              </button>
            ))}
          </div>
        </header>

        {/* Main Content Area */}
        <main className="main-content">
          {activeTab === 'dashboard' && <PerformanceDashboard metrics={metrics} />}
          {activeTab === 'events' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2">
                <EventStream events={events} />
              </div>
              <div>
                <StateViewer entityId={selectedEntity} />
              </div>
            </div>
          )}
          {activeTab === 'strategies' && <StrategyMarketplace />}
          {activeTab === 'security' && (
            <div className="glass-card p-6">
              <h2 className="text-xl font-semibold mb-4 text-cyan-400">Security & RBAC</h2>
              <p className="text-gray-400">API Key Management & Role-Based Access Control</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default App
