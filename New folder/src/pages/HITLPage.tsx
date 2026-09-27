import { useMemo, useState } from 'react'
import { CheckCircle2, History, ShieldAlert } from 'lucide-react'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { HITLQueue } from '@/components/hitl/HITLQueue'
import { Badge } from '@/components/ui/Badge'
import { cn, formatRelative, getAgentMeta, idShort } from '@/lib/utils'
import { usePendingApprovals, useHITLHistory, useApproveApproval, useRejectApproval } from '@/hooks/useHITL'
import { useTasksList } from '@/hooks/useTasks'

type Tab = 'pending' | 'history'

export function HITLPage() {
  const [tab, setTab] = useState<Tab>('pending')
  const [actingId, setActingId] = useState<string | null>(null)
  const { data: pending, isLoading: pendingLoading } = usePendingApprovals()
  const { data: history, isLoading: historyLoading } = useHITLHistory()
  const { data: tasks } = useTasksList()
  const approve = useApproveApproval()
  const reject = useRejectApproval()

  const goals = useMemo(() => {
    const map: Record<string, string> = {}
    for (const t of tasks ?? []) map[t.id] = t.goal
    return map
  }, [tasks])

  return (
    <PageWrapper>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg border border-border bg-elevated/50 p-0.5">
          {(
            [
              { key: 'pending', label: `Pending (${pending?.length ?? 0})` },
              { key: 'history', label: 'History' },
            ] as Array<{ key: Tab; label: string }>
          ).map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                'rounded-md px-3.5 py-1.5 text-xs font-medium transition-colors',
                tab === t.key ? 'bg-brand text-[#06281c]' : 'text-text-secondary hover:text-text-primary',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'pending' ? (
        <div className="mt-4">
          {pendingLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-72 w-full" />
            </div>
          ) : pending && pending.length > 0 ? (
            <>
              <div className="mb-4 flex items-center gap-2.5 rounded-lg border border-error/30 bg-error/10 px-4 py-3">
                <ShieldAlert className="h-4 w-4 shrink-0 text-error" />
                <p className="text-sm font-medium text-error">
                  {pending.length} action{pending.length > 1 ? 's' : ''} require your approval
                </p>
              </div>
              <HITLQueue
                approvals={pending}
                goals={goals}
                approvingId={actingId && approve.isPending ? actingId : null}
                rejectingId={actingId && reject.isPending ? actingId : null}
                onApprove={(a) => {
                  setActingId(a.approval_id)
                  approve.mutate(a.approval_id, { onSettled: () => setActingId(null) })
                }}
                onReject={(a) => {
                  setActingId(a.approval_id)
                  reject.mutate(a.approval_id, { onSettled: () => setActingId(null) })
                }}
              />
            </>
          ) : (
            <Card>
              <EmptyState
                icon={<CheckCircle2 className="h-6 w-6 text-success" />}
                title="No approvals needed"
                description="NexusAI is running autonomously. You'll be notified here when an agent needs your approval for a risky action."
              />
            </Card>
          )}
        </div>
      ) : (
        <div className="mt-4">
          <Card title="Approval History" padded={false}>
            {historyLoading || !history ? (
              <div className="space-y-2 p-4">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : history.length === 0 ? (
              <EmptyState icon={<History className="h-6 w-6" />} title="No approvals yet" description="Decisions you make on pending approvals will appear here." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-border bg-elevated/40 text-left text-[11px] uppercase tracking-wide text-text-muted">
                      <th className="px-4 py-2.5 font-medium">Action</th>
                      <th className="px-3 py-2.5 font-medium">Agent</th>
                      <th className="px-3 py-2.5 font-medium">Decision</th>
                      <th className="px-3 py-2.5 font-medium">Decided by</th>
                      <th className="px-3 py-2.5 text-right font-medium">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => {
                      const agent = getAgentMeta(h.agent_type)
                      return (
                        <tr key={h.approval_id} className="border-b border-border/50 last:border-0">
                          <td className="px-4 py-2.5">
                            <div>
                              <p className="font-mono text-xs text-brand-light">{h.tool_name}</p>
                              <p className="max-w-[240px] truncate text-xs text-text-muted">{h.goal}</p>
                            </div>
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge tone="neutral" dot dotColor={agent.color}>
                              {agent.short}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge tone={h.decision === 'approved' ? 'success' : 'error'}>
                              {h.decision === 'approved' ? '✓ Approved' : '✗ Rejected'}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 text-text-secondary">you</td>
                          <td className="px-3 py-2.5 text-right text-xs text-text-muted">
                            {formatRelative(h.decided_at)}
                            <span className="ml-2 font-mono text-[10px]">{idShort(h.task_id)}</span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
    </PageWrapper>
  )
}
