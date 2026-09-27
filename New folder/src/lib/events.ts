import type { TraceEvent, TraceEventType } from '@/types/trace'
import { formatCost, formatDuration, getAgentMeta, uid } from '@/lib/utils'

interface EventStyle {
  color: string
  icon: 'plain' | 'success' | 'error' | 'warning'
}

/**
 * Human-readable message + color for each trace event type.
 * This is the display vocabulary of the live activity feed.
 */
export function describeEvent(event: TraceEvent): string {
  const d = event.event_data ?? {}
  const agent = event.agent_type ? getAgentMeta(event.agent_type) : null
  const agentName = agent ? agent.short : 'Agent'
  const cost = typeof d.cost_usd === 'number' ? formatCost(d.cost_usd) : null
  const duration =
    typeof d.duration_seconds === 'number' ? formatDuration(d.duration_seconds) : null

  switch (event.event_type) {
    case 'task_started':
      return 'Task received and queued'
    case 'failure_patterns_checked':
      return `Checked failure patterns · ${(d.patterns_found as number) ?? 0} known issues`
    case 'routing_complete': {
      const count = (d.agent_count as number) ?? (d.agents as string[])?.length ?? 0
      const conf = typeof d.confidence === 'number' ? ` (confidence ${Math.round(d.confidence * 100)}%)` : ''
      return `Router selected ${count} agents${conf}`
    }
    case 'cost_estimated':
      return `Estimated cost: ${cost ?? '—'}`
    case 'agent_spawned': {
      const group = d.group as string[] | undefined
      if (group && group.length > 1) return `${group.map((g) => getAgentMeta(g).short).join(' | ')} started (parallel)`
      return `${agentName} Agent started`
    }
    case 'agent_thinking':
      return `${agentName}: ${(d.note as string) ?? 'Analyzing requirements…'}`
    case 'agent_tool_called':
      return `${agentName}: Tool ${(d.tool as string) ?? 'execute_code'} called`
    case 'agent_tool_result':
      return `${agentName}: Tool result ${(d.ok as boolean) ? 'ok' : 'with issues'}`
    case 'agent_memory_retrieved':
      return `${agentName}: Retrieved ${(d.memories as number) ?? 1} memory entr${(d.memories as number) === 1 ? 'y' : 'ies'}`
    case 'hitl_required':
      return `⚠ Approval required for ${(d.tool as string) ?? 'action'}`
    case 'hitl_resolved':
      return `✓ ${(d.decision as string) ?? 'Resolved'} by ${(d.by as string) ?? 'user'}`
    case 'agent_completed': {
      const parts: string[] = []
      if (cost) parts.push(cost)
      if (duration) parts.push(duration)
      return parts.length ? `${agentName} Agent finished (${parts.join(', ')})` : `${agentName} Agent finished`
    }
    case 'hallucination_check':
      return `Hallucination check: ${(d.score as number) != null ? (d.score as number).toFixed(2) : 'clean'}`
    case 'quality_check':
      return `Quality score: ${(d.score as number) ?? 0}/100 ${(d.passed as boolean) ? '✓' : ''}`
    case 'learning_stored':
      return `Learning stored to memory (${(d.entries as number) ?? 1} entries)`
    case 'task_completed': {
      const parts = [cost && `Total: ${cost}`, duration && `${duration}`].filter(Boolean)
      return `✓ Task complete${parts.length ? ` — ${parts.join(' · ')}` : ''}`
    }
    case 'task_failed':
      return `✗ Task failed: ${(d.error as string) ?? 'unknown error'}`
    default:
      return event.event_type
  }
}

const STYLES: Record<TraceEventType, EventStyle> = {
  task_started: { color: 'var(--text-secondary)', icon: 'plain' },
  failure_patterns_checked: { color: 'var(--text-secondary)', icon: 'plain' },
  routing_complete: { color: 'var(--brand-primary)', icon: 'plain' },
  cost_estimated: { color: 'var(--status-info)', icon: 'plain' },
  agent_spawned: { color: 'var(--brand-secondary)', icon: 'plain' },
  agent_thinking: { color: 'var(--brand-secondary)', icon: 'plain' },
  agent_tool_called: { color: 'var(--status-warning)', icon: 'warning' },
  agent_tool_result: { color: 'var(--text-secondary)', icon: 'plain' },
  agent_memory_retrieved: { color: 'var(--status-info)', icon: 'plain' },
  hitl_required: { color: 'var(--status-error)', icon: 'error' },
  hitl_resolved: { color: 'var(--status-success)', icon: 'success' },
  agent_completed: { color: 'var(--status-success)', icon: 'success' },
  hallucination_check: { color: 'var(--status-info)', icon: 'plain' },
  quality_check: { color: 'var(--status-success)', icon: 'success' },
  learning_stored: { color: 'var(--text-secondary)', icon: 'plain' },
  task_completed: { color: 'var(--status-success)', icon: 'success' },
  task_failed: { color: 'var(--status-error)', icon: 'error' },
}

export function eventStyle(eventType: TraceEventType): EventStyle {
  return STYLES[eventType] ?? { color: 'var(--text-secondary)', icon: 'plain' }
}

/** Rebuild a TraceEvent from a raw WebSocket payload (which spreads the event fields). */
export function traceEventFromWS(taskId: string, data: Record<string, unknown>): TraceEvent {
  const eventType = (data.event_type as TraceEventType) ?? (data.event as TraceEventType) ?? 'task_started'
  return {
    id: (data.id as string) ?? uid(),
    task_id: taskId,
    event_type: eventType,
    event_data: (data.event_data as Record<string, unknown>) ?? data,
    agent_type: (data.agent_type as string) ?? null,
    timestamp: (data.timestamp as string) ?? new Date().toISOString(),
    sequence_number:
      (data.sequence_number as number) ?? (data.sequence as number) ?? Date.now(),
  }
}
