import { AgentAvatar } from '@/components/agent/AgentAvatar'
import { getAgentMeta, formatRelative, truncate } from '@/lib/utils'
import type { MemoryResult } from '@/types/memory'

export function MemoryResultCard({ result }: { result: MemoryResult }) {
  const { metadata, similarity_score } = result
  const agents = metadata.agent_type ? [metadata.agent_type] : []
  const pct = Math.round(similarity_score * 100)

  return (
    <div className="card p-4 transition-colors hover:border-border/80">
      <div className="flex items-center justify-between gap-3">
        <span
          className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold tabular-nums"
          style={{
            color: pct >= 85 ? 'var(--status-success)' : pct >= 65 ? 'var(--status-warning)' : 'var(--text-secondary)',
            background: 'var(--bg-elevated)',
            borderColor: 'var(--bg-border)',
          }}
        >
          {pct}% match
        </span>
        {metadata.timestamp && <span className="text-xs text-text-muted">{formatRelative(metadata.timestamp)}</span>}
      </div>

      <p className="mt-3 text-sm font-medium leading-relaxed text-text-primary">{truncate(result.content, 220)}</p>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-muted">
        {agents.length > 0 && (
          <span className="flex items-center gap-1.5">
            <AgentAvatar agentType={agents[0]} size="sm" />
            {getAgentMeta(agents[0]).label}
          </span>
        )}
        {metadata.quality_score != null && <span>Quality: {metadata.quality_score}/100</span>}
        <span className="font-mono text-[11px]">{metadata.task_id ? truncate(metadata.task_id, 16) : ''}</span>
      </div>
    </div>
  )
}
