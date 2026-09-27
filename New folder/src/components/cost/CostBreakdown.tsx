import { useMemo } from 'react'
import { getAgentMeta, formatCost, formatTokens, formatNumber } from '@/lib/utils'
import type { CostRecord } from '@/types/cost'

export interface CostBreakdownProps {
  records?: CostRecord[]
  estimatedUsd?: number | null
  loading?: boolean
}

export function CostBreakdown({ records = [], estimatedUsd, loading }: CostBreakdownProps) {
  const total = useMemo(() => records.reduce((s, r) => s + r.cost_usd, 0), [records])

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-8" />
        ))}
      </div>
    )
  }

  if (records.length === 0) {
    return <p className="py-2 text-sm text-text-muted">No cost records yet — costs appear as agents run.</p>
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between text-sm">
        <span className="text-text-secondary">
          Estimated <span className="tabular-nums text-text-primary">{formatCost(estimatedUsd)}</span>
        </span>
        <span className="text-text-secondary">
          Actual <span className="font-semibold tabular-nums text-text-primary">{formatCost(total)}</span>
        </span>
      </div>

      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-elevated/60 text-left text-[11px] uppercase tracking-wide text-text-muted">
              <th className="px-3 py-2 font-medium">Agent</th>
              <th className="hidden px-3 py-2 font-medium sm:table-cell">Model</th>
              <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Tokens</th>
              <th className="px-3 py-2 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => {
              const meta = getAgentMeta(r.agent_type)
              return (
                <tr key={r.id} className="border-b border-border/50 last:border-0">
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: meta.color }} />
                      <span className="text-text-primary">{meta.short}</span>
                    </span>
                  </td>
                  <td className="hidden px-3 py-2 text-xs text-text-muted sm:table-cell">{r.llm_model}</td>
                  <td className="hidden px-3 py-2 text-right tabular-nums text-text-secondary md:table-cell">
                    {formatTokens(r.input_tokens + r.output_tokens)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-text-primary">{formatCost(r.cost_usd)}</td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr className="bg-elevated/60">
              <td className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">Total</td>
              <td className="hidden sm:table-cell" />
              <td className="hidden px-3 py-2 text-right tabular-nums text-text-secondary md:table-cell">
                {formatNumber(records.reduce((s, r) => s + r.input_tokens + r.output_tokens, 0))}
              </td>
              <td className="px-3 py-2 text-right font-semibold tabular-nums text-text-primary">{formatCost(total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}
