import { ArrowRight, Loader2 } from 'lucide-react'
import { AgentAvatar } from '@/components/agent/AgentAvatar'
import { getAgentMeta } from '@/lib/utils'
import type { RoutingDecision } from '@/types/task'
import type { AgentRunStatus } from '@/types/agent'
import type { TraceEvent } from '@/types/trace'

export interface AgentTimelineProps {
  routing: RoutingDecision | null
  statuses?: Record<string, AgentRunStatus>
  events?: TraceEvent[]
  taskStatus?: string
}

interface Block {
  agent: string
  status: AgentRunStatus
  durationSec?: number
}

export function AgentTimeline({ routing, statuses = {}, events = [], taskStatus }: AgentTimelineProps) {
  if (!routing || routing.agents.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-elevated/40 px-4 py-3 text-sm text-text-muted">
        Routing plan not available yet.
      </div>
    )
  }

  // Duration lookup: last agent_completed event for each agent.
  const durations: Record<string, number> = {}
  for (const e of events) {
    if (e.event_type === 'agent_completed' && e.agent_type) {
      const d = e.event_data.duration_seconds
      if (typeof d === 'number') durations[e.agent_type] = d
    }
  }

  const buildBlocks = (agents: string[]): Block[] =>
    agents.map((a) => ({
      agent: a,
      status: statuses[a] ?? (taskStatus === 'completed' ? 'done' : taskStatus === 'failed' ? 'failed' : 'waiting'),
      durationSec: durations[a],
    }))

  const sequential = routing.sequential.filter(Boolean)
  const groups = routing.parallel_groups ?? []
  const hasParallel = groups.length > 0

  return (
    <div className="flex flex-wrap items-center gap-2">
      {sequential.map((agent, i) => (
        <div key={`seq-${agent}`} className="flex items-center gap-2">
          {i > 0 && <ArrowRight className="h-4 w-4 text-text-muted" />}
          <AgentBlock block={buildBlocks(sequential)[i]} />
        </div>
      ))}

      {hasParallel && sequential.length > 0 && <ArrowRight className="h-4 w-4 text-text-muted" />}

      {hasParallel && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-border bg-elevated/40 px-2.5 py-2">
          {groups.map((group, gi) => (
            <div key={`g-${gi}`} className="flex flex-wrap items-center gap-2">
              {gi > 0 && <span className="text-text-muted">·</span>}
              {group.map((agent, ai) => (
                <div key={agent} className="flex items-center gap-2">
                  {ai > 0 && <span className="text-xs text-text-muted">+</span>}
                  <AgentBlock block={buildBlocks(group)[ai]} compact />
                </div>
              ))}
            </div>
          ))}
          <span className="ml-1 text-[10px] uppercase tracking-wide text-text-muted">parallel</span>
        </div>
      )}
    </div>
  )
}

function AgentBlock({ block, compact }: { block: Block; compact?: boolean }) {
  const meta = getAgentMeta(block.agent)
  const isRunning = block.status === 'running'
  return (
    <div
      className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 transition-colors"
      style={{
        borderColor: isRunning
          ? 'var(--brand-primary)'
          : block.status === 'failed'
            ? 'color-mix(in srgb, var(--status-error) 40%, transparent)'
            : 'var(--bg-border)',
        background: isRunning ? 'color-mix(in srgb, var(--brand-primary) 8%, transparent)' : 'var(--bg-surface)',
      }}
      title={meta.label}
    >
      <AgentAvatar agentType={block.agent} size="sm" />
      {!compact && <span className="text-xs font-medium text-text-primary">{meta.short}</span>}
      {isRunning ? (
        <Loader2 className="h-3 w-3 animate-spin text-brand" />
      ) : block.status === 'done' ? (
        <span className="text-[10px] tabular-nums text-success">{block.durationSec != null ? `${block.durationSec}s` : '✓'}</span>
      ) : block.status === 'failed' ? (
        <span className="text-[10px] text-error">✗</span>
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-text-muted/50" />
      )}
    </div>
  )
}
