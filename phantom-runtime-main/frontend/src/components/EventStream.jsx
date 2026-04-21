import { useEffect, useRef } from 'react'
import { Activity, Hash, Clock } from 'lucide-react'

export default function EventStream({ events }) {
  const streamRef = useRef(null)

  useEffect(() => {
    if (streamRef.current && events.length > 0) {
      streamRef.current.scrollTop = 0
    }
  }, [events])

  return (
    <div className="glass-card p-6 h-[calc(100vh-250px)]" data-testid="event-stream">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-cyan-400" />
          <h2 className="text-lg font-semibold text-cyan-400">Live Event Stream</h2>
        </div>
        <span className="text-sm text-gray-500 terminal-text">{events.length} events buffered</span>
      </div>

      <div 
        ref={streamRef}
        className="space-y-2 overflow-y-auto h-[calc(100%-60px)] pr-2"
        style={{ scrollBehavior: 'smooth' }}
      >
        {events.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-500">
            <p className="text-sm">Waiting for events...</p>
          </div>
        )}

        {events.map((event, index) => (
          <div
            key={index}
            className="event-stream-item glass-card p-4 border border-gray-700/50 hover:border-cyan-500/50 transition-all"
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></div>
                <span className="text-sm font-mono text-cyan-400">{event.event_type || 'EVENT'}</span>
              </div>
              <span className="text-xs text-gray-500 terminal-text">
                {event.created_at ? new Date(event.created_at).toLocaleTimeString() : 'now'}
              </span>
            </div>

            <div className="flex items-center gap-3 mb-2 text-xs text-gray-400">
              <div className="flex items-center gap-1">
                <Hash className="w-3 h-3" />
                <span className="terminal-text">{event.entity_id}</span>
              </div>
              {event.event_hash && (
                <div className="flex items-center gap-1">
                  <span className="terminal-text">{event.event_hash.slice(0, 12)}...</span>
                </div>
              )}
            </div>

            <pre className="text-xs bg-black/30 p-3 rounded border border-gray-800 overflow-x-auto terminal-text">
              {JSON.stringify(event.payload || event, null, 2)}
            </pre>
          </div>
        ))}
      </div>
    </div>
  )
}
