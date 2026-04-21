import { useState, useEffect, useRef, useCallback } from 'react'

export function useWebSocket() {
  const [events, setEvents] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [isConnected, setIsConnected] = useState(false)
  const wsEvents = useRef(null)
  const wsMetrics = useRef(null)
  const reconnectTimeout = useRef(null)

  const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'https://phantom-runtime.preview.emergentagent.com'
  const WS_URL = BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://')

  const connectEventStream = useCallback(() => {
    if (wsEvents.current?.readyState === WebSocket.OPEN) return

    try {
      wsEvents.current = new WebSocket(`${WS_URL}/ws/events`)

      wsEvents.current.onopen = () => {
        console.log('✓ Event stream connected')
        setIsConnected(true)
      }

      wsEvents.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'new_event') {
            setEvents(prev => [data.data, ...prev].slice(0, 100))
          }
        } catch (err) {
          console.error('WebSocket message error:', err)
        }
      }

      wsEvents.current.onclose = () => {
        console.log('Event stream disconnected')
        setIsConnected(false)
        // Reconnect after 3 seconds
        reconnectTimeout.current = setTimeout(connectEventStream, 3000)
      }

      wsEvents.current.onerror = (error) => {
        console.error('WebSocket error:', error)
        wsEvents.current?.close()
      }
    } catch (err) {
      console.error('WebSocket connection error:', err)
      reconnectTimeout.current = setTimeout(connectEventStream, 3000)
    }
  }, [WS_URL])

  const connectMetricsStream = useCallback(() => {
    if (wsMetrics.current?.readyState === WebSocket.OPEN) return

    try {
      wsMetrics.current = new WebSocket(`${WS_URL}/ws/metrics`)

      wsMetrics.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'metrics_update') {
            setMetrics(data.data)
          }
        } catch (err) {
          console.error('Metrics message error:', err)
        }
      }

      wsMetrics.current.onclose = () => {
        reconnectTimeout.current = setTimeout(connectMetricsStream, 3000)
      }
    } catch (err) {
      console.error('Metrics WebSocket error:', err)
    }
  }, [WS_URL])

  useEffect(() => {
    connectEventStream()
    connectMetricsStream()

    return () => {
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current)
      }
      wsEvents.current?.close()
      wsMetrics.current?.close()
    }
  }, [connectEventStream, connectMetricsStream])

  return { events, metrics, isConnected }
}
