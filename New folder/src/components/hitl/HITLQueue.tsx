import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, Check, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { HITLExpiryText } from '@/components/hitl/HITLBanner'
import { HITLModal } from '@/components/hitl/HITLModal'
import { getAgentMeta, idShort } from '@/lib/utils'
import type { HITLApproval } from '@/types/hitl'

export interface HITLQueueProps {
  approvals: HITLApproval[]
  goals?: Record<string, string>
  approvingId?: string | null
  rejectingId?: string | null
  onApprove: (approval: HITLApproval) => void
  onReject: (approval: HITLApproval) => void
}

export function HITLQueue({ approvals, goals = {}, approvingId, rejectingId, onApprove, onReject }: HITLQueueProps) {
  const [confirm, setConfirm] = useState<{ approval: HITLApproval; action: 'approve' | 'reject' } | null>(null)

  return (
    <div className="space-y-4">
      {approvals.map((approval) => {
        const agent = getAgentMeta(approval.agent_type)
        const params = JSON.stringify(approval.tool_params, null, 2)
        return (
          <div key={approval.approval_id} className="card overflow-hidden">
            <div className="flex flex-wrap items-center gap-2 border-b border-border bg-warning/5 px-4 py-3">
              <AlertTriangle className="h-4 w-4 text-warning" />
              <p className="text-sm font-semibold text-text-primary">
                <span style={{ color: agent.color }}>{agent.short}</span> Agent wants to <code className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-brand-light">{approval.tool_name}</code>
              </p>
            </div>

            <div className="space-y-3 p-4">
              <p className="text-sm text-text-secondary">{approval.tool_description}</p>

              <div className="overflow-hidden rounded-lg border border-border bg-base">
                <div className="border-b border-border bg-elevated/60 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">
                  Parameters
                </div>
                <pre className="max-h-48 overflow-auto p-3 font-mono text-xs leading-relaxed text-text-secondary">{params}</pre>
              </div>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <Link
                  to={`/tasks/${approval.task_id}`}
                  className="flex min-w-0 items-center gap-1 text-text-secondary transition-colors hover:text-brand-light"
                >
                  <span className="truncate">“{goals[approval.task_id] ?? 'Task'}”</span>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0" />
                </Link>
                <span className="font-mono text-xs text-text-muted">{idShort(approval.task_id)}</span>
                <span className="flex items-center gap-1.5 text-xs">
                  ⏱ Expires in <HITLExpiryText approval={approval} />
                </span>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  variant="success"
                  className="flex-1"
                  loading={approvingId === approval.approval_id}
                  disabled={rejectingId === approval.approval_id}
                  onClick={() => setConfirm({ approval, action: 'approve' })}
                >
                  <Check className="h-4 w-4" /> Approve
                </Button>
                <Button
                  variant="danger"
                  className="flex-1"
                  loading={rejectingId === approval.approval_id}
                  disabled={approvingId === approval.approval_id}
                  onClick={() => setConfirm({ approval, action: 'reject' })}
                >
                  <X className="h-4 w-4" /> Reject
                </Button>
              </div>
            </div>
          </div>
        )
      })}

      <HITLModal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        action={confirm?.action ?? 'approve'}
        loading={
          (confirm?.action === 'approve' && approvingId === confirm?.approval.approval_id) ||
          (confirm?.action === 'reject' && rejectingId === confirm?.approval.approval_id)
        }
        detail={
          confirm
            ? `${getAgentMeta(confirm.approval.agent_type).label} will ${confirm.approval.tool_name} — “${confirm.approval.tool_description}”`
            : undefined
        }
        onConfirm={() => {
          if (!confirm) return
          if (confirm.action === 'approve') onApprove(confirm.approval)
          else onReject(confirm.approval)
          setConfirm(null)
        }}
      />
    </div>
  )
}
