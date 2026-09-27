import { useEffect, useRef, useState } from 'react'
import { formatCost } from '@/lib/utils'

export interface CostMeterProps {
  value: number
  max?: number
  label?: string
}

/** Live cost ticker — animates each time a cost event arrives over WebSocket. */
export function CostMeter({ value, max, label = 'Live cost' }: CostMeterProps) {
  const [display, setDisplay] = useState(value)
  const [pulse, setPulse] = useState(false)
  const prev = useRef(value)

  useEffect(() => {
    if (value !== prev.current) {
      prev.current = value
      setDisplay(value)
      setPulse(true)
      const t = window.setTimeout(() => setPulse(false), 400)
      return () => window.clearTimeout(t)
    }
    setDisplay(value)
    return undefined
  }, [value])

  const pct = max && max > 0 ? Math.min(100, (value / max) * 100) : 0

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-elevated/50 px-3 py-2">
      <span className={`text-xs font-medium uppercase tracking-wide text-text-muted ${pulse ? 'text-brand-light' : ''}`}>
        {label}
      </span>
      <span
        className="text-lg font-bold tabular-nums text-brand-light transition-transform"
        style={{ transform: pulse ? 'scale(1.06)' : 'scale(1)' }}
      >
        {formatCost(display)}
      </span>
      <div className="ml-auto h-1.5 w-20 overflow-hidden rounded-full bg-elevated">
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand to-brand-light transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
