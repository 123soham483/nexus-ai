import { AlertTriangle, Check, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { getAgentMeta } from '@/lib/utils'
import { formatCountdown, useCountdown } from '@/hooks/useCountdown'
import { cn } from '@/lib/utils'
import type { HITLApproval } from '@/types/hitl'

export interface HITLBannerProps {
  approval: HITLApproval
  approving?: boolean
  rejecting?: boolean
  onApprove: () => void
  onReject: () => void
}

export function HITLBanner({ approval, approving, rejecting, onApprove, onReject }: HITLBannerProps) {
  const remaining = useCountdown(approval.expires_at)
  const urgent = remaining < 60
  const agent = getAgentMeta(approval.agent_type)
  const params = JSON.stringify(approval.tool_params, null, 2)

  return (
    <div className="card overflow-hidden border-warning/40">
      <div className="flex items-center gap-2.5 border-b border-warning/30 bg-warning/10 px-4 py-3">
        <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
        <p className="text-sm font-semibold text-warning">Human approval required</p>
        <span className="ml-auto flex items-center gap-1.5 text-sm tabular-nums" style={{ color: urgent ? 'var(--status-error)' : 'var(--status-warning)' }}>
          <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full" style={{ background: urgent ? 'var(--status-error)' : 'var(--status-warning)' }} />
          Expires in {formatCountdown(remaining)}
        </span>
      </div>

      <div className="space-y-3 p-4">
        <div className="flex items-center gap-2 text-sm">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: agent.color }} />
          <span className="font-medium text-text-primary">{agent.label}</span>
          <span className="text-text-secondary">wants to</span>
          <code className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-brand-light">{approval.tool_name}</code>
        </div>

        <p className="text-sm text-text-secondary">{approval.tool_description}</p>

        <div className="overflow-hidden rounded-lg border border-border bg-base">
          <div className="border-b border-border bg-elevated/60 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Parameters
          </div>
          <pre className="max-h-44 overflow-auto p-3 font-mono text-xs leading-relaxed text-text-secondary">{params}</pre>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="success" className="flex-1" loading={approving} onClick={onApprove} disabled={rejecting}>
            <Check className="h-4 w-4" /> Approve
          </Button>
          <Button variant="danger" className="flex-1" loading={rejecting} onClick={onReject} disabled={approving}>
            <X className="h-4 w-4" /> Reject
          </Button>
        </div>
      </div>
    </div>
  )
}

export function HITLExpiryText({ approval, className }: { approval: HITLApproval; className?: string }) {
  const remaining = useCountdown(approval.expires_at)
  return (
    <span className={cn('tabular-nums', remaining < 60 ? 'text-error' : 'text-warning', className)}>
      {formatCountdown(remaining)}
    </span>
  )
}
