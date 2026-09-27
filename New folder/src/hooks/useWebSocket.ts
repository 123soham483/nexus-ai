import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { wsManager } from '@/lib/websocket'
import { useTaskStore } from '@/store/taskStore'
import { useNotificationStore } from '@/store/notificationStore'
import { traceEventFromWS } from '@/lib/events'
import type { TraceEventType } from '@/types/trace'

/**
 * Subscribes to the live event stream for a task. Events are pushed into
 * taskStore.liveEvents and mirrored into agent statuses / running cost.
 */
export function useTaskWebSocket(taskId: string | null | undefined) {
  const qc = useQueryClient()

  useEffect(() => {
    if (!taskId) return
    useTaskStore.getState().clearLiveState()
    useTaskStore.getState().setActiveTask(taskId)

    const push = useNotificationStore.getState().push

    const unsub = wsManager.on(taskId, '*', (data) => {
      const eventType = (data.event_type as TraceEventType) ?? (data.event as TraceEventType)
      const ev = traceEventFromWS(taskId, data)

      const store = useTaskStore.getState()
      store.addLiveEvent(ev)

      switch (eventType) {
        case 'agent_spawned':
        case 'agent_thinking':
        case 'agent_tool_called':
          if (ev.agent_type) store.updateAgentStatus(ev.agent_type, 'running')
          break
        case 'agent_completed': {
          if (ev.agent_type) store.updateAgentStatus(ev.agent_type, 'done')
          const cost = data.cost_usd
          if (typeof cost === 'number') {
            useTaskStore.setState((s) => ({ liveCost: Math.round((s.liveCost + cost) * 100) / 100 }))
          }
          break
        }
        case 'hitl_required':
          push({ kind: 'hitl', title: 'Human approval required', body: `Agent ${ev.agent_type ?? ''} needs your approval` })
          toast('⚠ Human approval required', { icon: '🛡️' })
          break
        case 'task_completed':
          void qc.invalidateQueries({ queryKey: ['task', taskId] })
          void qc.invalidateQueries({ queryKey: ['task-trace', taskId] })
          void qc.invalidateQueries({ queryKey: ['task-cost', taskId] })
          void qc.invalidateQueries({ queryKey: ['tasks'] })
          push({ kind: 'task', title: 'Task completed' })
          toast.success('Task completed')
          break
        case 'task_failed':
          void qc.invalidateQueries({ queryKey: ['task', taskId] })
          void qc.invalidateQueries({ queryKey: ['task-trace', taskId] })
          void qc.invalidateQueries({ queryKey: ['task-cost', taskId] })
          void qc.invalidateQueries({ queryKey: ['tasks'] })
          push({ kind: 'task', title: 'Task failed' })
          toast.error('Task failed')
          break
        default:
          break
      }
    })

    wsManager.connect(taskId)
    return () => unsub()
  }, [taskId, qc])
}
