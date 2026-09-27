import { AlertTriangle } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { getAgentMeta, formatRelative } from '@/lib/utils'
import type { FailurePattern } from '@/types/memory'

export function FailurePatternCard({ pattern }: { pattern: FailurePattern }) {
  const agent = getAgentMeta(pattern.failed_agent)
  return (
    <div className="card border-error/20 p-4">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-error/10 text-error">
          <AlertTriangle className="h-4 w-4" />
        </span>
        <h4 className="text-sm font-semibold text-text-primary">Failure Pattern</h4>
        <span className="ml-auto text-xs text-text-muted">{formatRelative(pattern.stored_at)}</span>
      </div>

      <p className="mt-3 text-sm text-text-primary">“{pattern.goal}”</p>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-text-muted">Failed at:</span>
        <Badge tone="error" dot dotColor={agent.color}>
          {agent.short} Agent
        </Badge>
      </div>

      <div className="mt-2.5 rounded-lg border border-border bg-base px-3 py-2 font-mono text-xs text-error/90">
        {pattern.error}
      </div>
    </div>
  )
}
