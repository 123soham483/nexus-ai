import type { TraceEvent } from '@/types/trace'
import { getLiveScript, applyScriptEvent, buildFeedEvent } from '@/lib/mockData'
import { useConnectionStore } from '@/store/connectionStore'

/** Registry of open mock sockets — lets the mock API push events (e.g. HITL resolution). */
export const mockSockets = new Map<string, MockWebSocket>()

export function dispatchMockEvent(taskId: string, event: TraceEvent): void {
  applyScriptEvent(taskId, event)
  mockSockets.get(taskId)?.emit(event)
}

export class MockWebSocket {
  taskId: string
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  private timers: number[] = []
  private idx = 0

  constructor(taskId: string) {
    this.taskId = taskId
    mockSockets.set(taskId, this)
    window.setTimeout(() => {
      this.readyState = 1
      useConnectionStore.getState().setStatus('connected')
      this.onopen?.()
    }, 200)
    this.schedule()
  }

  private schedule(): void {
    // Global live feed (dashboard) — random cross-task events forever.
    if (this.taskId === '__live__') {
      const loop = () => {
        this.emit(buildFeedEvent())
        this.timers.push(window.setTimeout(loop, 1600 + Math.random() * 2400))
      }
      this.timers.push(window.setTimeout(loop, 1200))
      return
    }

    // Task-specific script — replay remaining trace events for live tasks.
    const script = getLiveScript(this.taskId)
    if (!script || script.length === 0) return
    const play = () => {
      if (this.idx >= script.length) return
      const ev = script[this.idx++]
      applyScriptEvent(this.taskId, ev)
      this.emit(ev)
      const next = script[this.idx]
      if (next) {
        const gap = new Date(next.timestamp).getTime() - new Date(ev.timestamp).getTime()
        const delay = Math.max(500, Math.min(3500, gap / 3 || 1200))
        this.timers.push(window.setTimeout(play, delay))
      }
    }
    this.timers.push(window.setTimeout(play, 800))
  }

  emit(event: TraceEvent): void {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify({ event: event.event_type, data: event }) })
    }
  }

  close(): void {
    this.readyState = 3
    this.timers.forEach((t) => window.clearTimeout(t))
    this.timers = []
    mockSockets.delete(this.taskId)
    this.onclose?.()
  }
}
