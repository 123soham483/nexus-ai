import { useEffect, useState } from 'react'
import { wsManager } from '@/lib/websocket'
import { MOCK_MODE, observability } from '@/lib/api'
import { traceEventFromWS } from '@/lib/events'
import type { TraceEvent } from '@/types/trace'

const FEED_ID = '__live__'

/**
 * Cross-task live feed for the dashboard. In mock mode this subscribes to a
 * synthetic event stream; against a real backend it polls recent traces.
 */
export function useLiveActivity(limit = 20): TraceEvent[] {
  const [events, setEvents] = useState<TraceEvent[]>([])

  useEffect(() => {
    if (MOCK_MODE) {
      const unsub = wsManager.on(FEED_ID, '*', (data) => {
        const ev = traceEventFromWS(FEED_ID, data)
        setEvents((prev) => [ev, ...prev].slice(0, limit))
      })
      wsManager.connect(FEED_ID)
      return () => {
        unsub()
        wsManager.disconnect(FEED_ID)
      }
    }

    let cancelled = false
    const poll = async () => {
      try {
        const res = await observability.traces()
        if (cancelled) return
        const recent = [...res.data].reverse().slice(0, limit)
        setEvents(recent)
      } catch {
        // Keep the last known events.
      }
    }
    void poll()
    const timer = window.setInterval(poll, 5000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [limit])

  return events
}
