import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Bell, ChevronDown, LogOut, Settings as SettingsIcon, User } from 'lucide-react'
import { formatCostCompact, initials } from '@/lib/utils'
import { useNotificationStore } from '@/store/notificationStore'
import { useAuthStore } from '@/store/authStore'
import { useAuth } from '@/hooks/useAuth'
import { useBudget } from '@/hooks/useCost'
import { ProgressBar } from '@/components/ui/ProgressBar'

const TITLES: Array<[RegExp, string]> = [
  [/^\/dashboard/, 'Dashboard'],
  [/^\/tasks\/new/, 'New Task'],
  [/^\/tasks\/\d+/, 'Task Detail'],
  [/^\/tasks/, 'Tasks'],
  [/^\/cost/, 'Cost & Budget'],
  [/^\/agents/, 'Agents'],
  [/^\/observability/, 'Observability'],
  [/^\/memory/, 'Memory'],
  [/^\/hitl/, 'Human Approvals'],
  [/^\/settings/, 'Settings'],
]

export function TopBar() {
  const location = useLocation()
  const navigate = useNavigate()
  const hitlCount = useNotificationStore((s) => s.hitlPendingCount)
  const user = useAuthStore((s) => s.user)
  const { logout } = useAuth()
  const { data: budget } = useBudget()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const title = TITLES.find(([re]) => re.test(location.pathname))?.[1] ?? 'NexusAI'
  const pct = budget ? Math.min(100, budget.percentage_used) : 0

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border bg-surface/90 px-4 backdrop-blur sm:px-6">
      <h1 className="text-base font-semibold text-text-primary">{title}</h1>

      <div className="flex items-center gap-2 sm:gap-3">
        {/* HITL bell */}
        <button
          onClick={() => navigate('/hitl')}
          className="relative rounded-lg p-2 text-text-secondary transition-colors hover:bg-elevated hover:text-text-primary"
          aria-label={`${hitlCount} pending approvals`}
        >
          <Bell className="h-[18px] w-[18px]" />
          {hitlCount > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-error px-1 text-[10px] font-bold text-white">
              {hitlCount}
            </span>
          )}
        </button>

        {/* Budget pill */}
        <Link
          to="/cost"
          className="hidden items-center gap-2 rounded-full border border-border bg-elevated/60 px-3 py-1.5 transition-colors hover:border-brand/40 sm:flex"
        >
          <span className="text-xs font-medium tabular-nums text-text-primary">
            {budget ? formatCostCompact(budget.current_month_spend_usd) : '…'}
            <span className="text-text-muted">
              {' / '}
              {budget ? formatCostCompact(budget.monthly_budget_usd) : ''}
            </span>
          </span>
          <ProgressBar value={pct} className="w-16" />
        </Link>

        {/* User menu */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((o) => !o)}
            className="flex items-center gap-2 rounded-lg p-1.5 transition-colors hover:bg-elevated"
            aria-label="User menu"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand/20 text-xs font-semibold text-brand-light">
              {initials(user?.full_name ?? user?.email)}
            </span>
            <ChevronDown className="hidden h-3.5 w-3.5 text-text-muted sm:block" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full mt-1.5 w-52 animate-fade-in overflow-hidden rounded-lg border border-border bg-elevated shadow-card">
              <div className="border-b border-border px-3 py-2.5">
                <p className="truncate text-sm font-medium text-text-primary">{user?.full_name ?? user?.email}</p>
                <p className="truncate text-xs text-text-muted">{user?.email}</p>
              </div>
              <button
                onClick={() => {
                  setMenuOpen(false)
                  navigate('/settings')
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-text-secondary transition-colors hover:bg-surface hover:text-text-primary"
              >
                <User className="h-4 w-4" /> Profile
              </button>
              <button
                onClick={() => {
                  setMenuOpen(false)
                  navigate('/settings')
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-text-secondary transition-colors hover:bg-surface hover:text-text-primary"
              >
                <SettingsIcon className="h-4 w-4" /> Settings
              </button>
              <button
                onClick={() => void logout()}
                className="flex w-full items-center gap-2.5 border-t border-border px-3 py-2 text-sm text-error transition-colors hover:bg-error/10"
              >
                <LogOut className="h-4 w-4" /> Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
