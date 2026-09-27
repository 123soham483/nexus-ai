import { AgentAvatar } from '@/components/agent/AgentAvatar'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { formatCost, formatDuration, formatPercent, formatRelative, getAgentMeta } from '@/lib/utils'
import type { AgentMetrics } from '@/types/agent'

export function AgentCard({ metrics }: { metrics: AgentMetrics }) {
  const meta = getAgentMeta(metrics.agent_type)

  return (
    <div className="card p-4 transition-colors hover:border-border/80">
      <div className="flex items-center gap-3">
        <AgentAvatar agentType={metrics.agent_type} size="lg" />
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <span className="h-2 w-2 rounded-full" style={{ background: meta.color }} />
            {meta.label}
          </p>
          <p className="text-xs text-text-muted">{metrics.most_common_model}</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm">
        <Stat label="Runs" value={metrics.total_runs.toLocaleString('en-IN')} />
        <Stat label="Success rate" value={formatPercent(metrics.success_rate)} valueColor={metrics.success_rate >= 90 ? 'var(--status-success)' : metrics.success_rate >= 70 ? 'var(--status-warning)' : 'var(--status-error)'} />
        <Stat label="Avg time" value={formatDuration(metrics.avg_duration_seconds)} />
        <Stat label="Avg cost" value={formatCost(metrics.avg_cost_usd)} />
        <Stat
          label="Quality"
          value={metrics.avg_quality_score === null ? '—' : `${metrics.avg_quality_score} / 100`}
        />
        <Stat
          label="Last run"
          value={metrics.last_run_at ? formatRelative(metrics.last_run_at) : '—'}
        />
      </div>

      <div className="mt-3.5">
        <div className="mb-1 flex justify-between text-[11px] text-text-muted">
          <span>Success</span>
          <span>{formatPercent(metrics.success_rate)}</span>
        </div>
        <ProgressBar
          value={metrics.success_rate}
          warnAt={70}
          dangerAt={90}
          className="h-1.5"
        />
      </div>
    </div>
  )
}

function Stat({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-text-muted">{label}</p>
      <p className="font-medium tabular-nums text-text-primary" style={{ color: valueColor }}>
        {value}
      </p>
    </div>
  )
}
