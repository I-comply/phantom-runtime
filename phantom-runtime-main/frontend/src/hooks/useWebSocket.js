import { useState, useEffect, useRef, useCallback } from 'react'
import { getApiKey, onApiKeyChange } from '../auth'

const CLOSE_UNAUTHORIZED = 4401

// Both sockets authenticate with the API key as their first message (a key in the URL would end up
// in logs). With no key, or a rejected key, they do not connect or retry: set a key and they start.
export function useWebSocket() {
  const [events, setEvents] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [isConnected, setIsConnected] = useState(false)
  const [authState, setAuthState] = useState(getApiKey() ? 'pending' : 'missing') // missing | pending | ok | rejected
  const [apiKey, setKey] = useState(getApiKey())
  const wsEvents = useRef(null)
  const wsMetrics = useRef(null)
  const timers = useRef({})

  const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'https://phantom-runtime.preview.emergentagent.com'
  const WS_URL = BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://')

  useEffect(() => onApiKeyChange((k) => {
    setKey(k)
    setAuthState(k ? 'pending' : 'missing')
  }), [])

  const open = useCallback((name, path, ref, handlers) => {
    if (!apiKey) return
    const connect = () => {
      if (ref.current?.readyState === WebSocket.OPEN) return
      try {
        const ws = new WebSocket(`${WS_URL}${path}`)
        ref.current = ws
        ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', api_key: apiKey }))
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            if (data.type === 'auth_ok') {
              setAuthState('ok')
              handlers.onAuthed?.()
            } else if (data.type === 'auth_error') {
              setAuthState('rejected')
            } else {
              handlers.onMessage?.(data)
            }
          } catch (err) {
            console.error(`${name} message error:`, err)
          }
        }
        ws.onclose = (e) => {
          handlers.onClosed?.()
          if (e.code === CLOSE_UNAUTHORIZED) return // wrong or missing key: retrying won't help
          timers.current[name] = setTimeout(connect, 3000)
        }
        ws.onerror = () => ws.close()
      } catch (err) {
        console.error(`${name} connection error:`, err)
        timers.current[name] = setTimeout(connect, 3000)
      }
    }
    connect()
  }, [WS_URL, apiKey])

  useEffect(() => {
    open('events', '/ws/events', wsEvents, {
      onAuthed: () => setIsConnected(true),
      onClosed: () => setIsConnected(false),
      onMessage: (data) => {
        if (data.type === 'new_event') setEvents((prev) => [data.data, ...prev].slice(0, 100))
      },
    })
    open('metrics', '/ws/metrics', wsMetrics, {
      onMessage: (data) => {
        if (data.type === 'metrics_update') setMetrics(data.data)
      },
    })
    const pending = timers.current
    return () => {
      Object.values(pending).forEach(clearTimeout)
      wsEvents.current?.close()
      wsMetrics.current?.close()
    }
  }, [open])

  return { events, metrics, isConnected, authState }
}
