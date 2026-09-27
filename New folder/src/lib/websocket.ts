import { useConnectionStore } from '@/store/connectionStore'
import { MOCK_MODE } from '@/lib/api'
import { MockWebSocket } from '@/lib/mockWs'

export interface SocketLike {
  readyState: number
  onopen: any
  onmessage: any
  onerror: any
  onclose: any
  close: () => void
}

type EventHandler = (data: Record<string, unknown>) => void

/**
 * Absolute WebSocket origin.
 *
 * Uses VITE_WS_BASE_URL when set; otherwise derives it from the page origin so
 * the socket follows the same host/port as the app (works with the Vite dev
 * proxy and with a production reverse proxy) without hardcoding a backend URL.
 */
function resolveWsBase(): string {
  const configured: string | undefined = import.meta.env.VITE_WS_BASE_URL
  if (configured) return configured
  if (typeof window === 'undefined') return ''
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}`
}

const WS_BASE: string = resolveWsBase()

class WebSocketManager {
  private sockets = new Map<string, SocketLike>()
  private handlers = new Map<string, Map<string, EventHandler[]>>()
  private intentional = new Set<string>()
  private reconnectTimers = new Map<string, number>()

  connect(taskId: string): SocketLike {
    if (this.sockets.has(taskId)) return this.sockets.get(taskId)!

    const ws: SocketLike = MOCK_MODE
      ? new MockWebSocket(taskId)
      : new WebSocket(`${WS_BASE}/ws/${taskId}`)

    ws.onmessage = (event: { data: string }) => {
      try {
        // Backend frame shape (app/websockets/broadcaster.py):
        //   { event: <trace_event_type>, data: <event_data>, timestamp: ISO }
        const message = JSON.parse(event.data) as {
          event?: string
          data?: Record<string, unknown>
          timestamp?: string
          sequence?: number
        }
        const eventType = message.event ?? 'unknown'
        const data = message.data ?? {}
        // Re-attach the server timestamp/sequence so the UI shows server time
        // rather than the moment the browser received the frame.
        const enriched = {
          ...data,
          timestamp: message.timestamp ?? new Date().toISOString(),
          ...(message.sequence !== undefined ? { sequence: message.sequence } : {}),
        }
        const taskHandlers = this.handlers.get(taskId)
        if (!taskHandlers) return
        taskHandlers.get(eventType)?.forEach((h) => h(enriched))
        taskHandlers.get('*')?.forEach((h) => h({ event: eventType, ...enriched }))
      } catch {
        // Malformed frame — ignore.
      }
    }

    ws.onopen = () => {
      useConnectionStore.getState().setStatus('connected')
      this.intentional.delete(taskId)
    }

    ws.onerror = () => {
      // close() follows; teardown happens there.
    }

    ws.onclose = () => {
      this.sockets.delete(taskId)
      if (this.intentional.has(taskId)) {
        this.intentional.delete(taskId)
        return
      }
      useConnectionStore.getState().setStatus('reconnecting')
      if (!this.reconnectTimers.has(taskId) && !MOCK_MODE) {
        const timer = window.setTimeout(() => {
          this.reconnectTimers.delete(taskId)
          this.connect(taskId)
        }, 3000)
        this.reconnectTimers.set(taskId, timer)
      }
    }

    this.sockets.set(taskId, ws)
    useConnectionStore.getState().register(taskId)
    return ws
  }

  on(taskId: string, eventType: string, handler: EventHandler): () => void {
    if (!this.handlers.has(taskId)) this.handlers.set(taskId, new Map())
    const taskHandlers = this.handlers.get(taskId)!
    if (!taskHandlers.has(eventType)) taskHandlers.set(eventType, [])
    taskHandlers.get(eventType)!.push(handler)
    return () => {
      const handlers = taskHandlers.get(eventType) ?? []
      const idx = handlers.indexOf(handler)
      if (idx > -1) handlers.splice(idx, 1)
    }
  }

  disconnect(taskId: string): void {
    this.intentional.add(taskId)
    const timer = this.reconnectTimers.get(taskId)
    if (timer) {
      window.clearTimeout(timer)
      this.reconnectTimers.delete(taskId)
    }
    this.sockets.get(taskId)?.close()
    this.sockets.delete(taskId)
    this.handlers.delete(taskId)
    useConnectionStore.getState().unregister(taskId)
  }
}

export const wsManager = new WebSocketManager()
