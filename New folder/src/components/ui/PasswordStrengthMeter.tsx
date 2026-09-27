import { Check, X } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface StrengthResult {
  score: 0 | 1 | 2 | 3
  label: string
  color: string
  checks: Array<{ label: string; ok: boolean }>
}

export function evaluatePassword(password: string): StrengthResult {
  const checks = [
    { label: '8+ characters', ok: password.length >= 8 },
    { label: 'Uppercase letter', ok: /[A-Z]/.test(password) },
    { label: 'Number', ok: /\d/.test(password) },
    { label: 'Special character', ok: /[^A-Za-z0-9]/.test(password) },
  ]
  const passed = checks.filter((c) => c.ok).length
  const score = (passed === 0 ? 0 : passed <= 1 ? 1 : passed <= 3 ? 2 : 3) as StrengthResult['score']
  const meta = [
    { label: 'Weak', color: 'var(--status-error)' },
    { label: 'Fair', color: 'var(--status-warning)' },
    { label: 'Strong', color: 'var(--status-success)' },
    { label: 'Strong', color: 'var(--status-success)' },
  ][score]
  return { score, label: meta.label, color: meta.color, checks }
}

export function PasswordStrengthMeter({ password }: { password: string }) {
  if (!password) return null
  const { score, label, color, checks } = evaluatePassword(password)
  return (
    <div className="mt-2">
      <div className="flex items-center gap-2">
        <div className="flex flex-1 gap-1">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-1 flex-1 rounded-full transition-colors"
              style={{ background: i < score ? color : 'var(--bg-border)' }}
            />
          ))}
        </div>
        <span className="text-xs font-medium" style={{ color }}>
          {label}
        </span>
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-1">
        {checks.map((c) => (
          <li key={c.label} className={cn('flex items-center gap-1.5 text-xs', c.ok ? 'text-text-secondary' : 'text-text-muted')}>
            {c.ok ? <Check className="h-3 w-3 text-success" /> : <X className="h-3 w-3 text-text-muted" />}
            {c.label}
          </li>
        ))}
      </ul>
    </div>
  )
}
