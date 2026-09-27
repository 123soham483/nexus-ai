import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Plus,
  ListTodo,
  Wallet,
  Bot,
  Activity,
  Brain,
  ShieldAlert,
  Settings,
  LogOut,
  ChevronsLeft,
  ChevronsRight,
  type LucideIcon,
} from 'lucide-react'
import { cn, initials } from '@/lib/utils'
import { useUIStore } from '@/store/uiStore'
import { useNotificationStore } from '@/store/notificationStore'
import { useAuthStore } from '@/store/authStore'
import { useAuth } from '@/hooks/useAuth'
import { Tooltip } from '@/components/ui/Tooltip'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  highlight?: boolean
  badge?: 'hitl'
}

const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/tasks/new', label: 'New Task', icon: Plus, highlight: true },
  { to: '/tasks', label: 'Tasks', icon: ListTodo },
  { to: '/cost', label: 'Cost', icon: Wallet },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/observability', label: 'Observability', icon: Activity },
  { to: '/memory', label: 'Memory', icon: Brain },
  { to: '/hitl', label: 'HITL', icon: ShieldAlert, badge: 'hitl' },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const toggle = useUIStore((s) => s.toggleSidebar)
  const hitlCount = useNotificationStore((s) => s.hitlPendingCount)
  const user = useAuthStore((s) => s.user)
  const { logout } = useAuth()
  const navigate = useNavigate()

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-border bg-surface transition-[width] duration-200 md:flex',
        collapsed ? 'w-16' : 'w-60',
      )}
    >
      {/* Logo */}
      <button
        onClick={() => navigate('/dashboard')}
        className="flex h-14 items-center gap-2.5 border-b border-border px-4"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand-light to-brand font-bold text-white">
          N
        </span>
        {!collapsed && (
          <span className="text-gradient-gold font-display text-lg font-bold tracking-wide">
            NexusAI
          </span>
        )}
      </button>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const link = (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/dashboard' || item.to === '/tasks'}
              className={({ isActive }) =>
                cn(
                  'group relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors',
                  collapsed && 'justify-center px-0',
                  isActive
                    ? 'bg-brand/15 text-brand-light shadow-[0_0_18px_var(--brand-glow)]'
                    : 'text-text-secondary hover:bg-elevated hover:text-text-primary',
                  item.highlight && 'border border-brand/25',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {item.badge === 'hitl' && hitlCount > 0 && (
                    <span
                      className={cn(
                        'flex h-4 min-w-4 items-center justify-center rounded-full bg-error px-1 text-[10px] font-bold text-white',
                        collapsed && 'absolute -right-0.5 -top-0.5',
                      )}
                    >
                      {hitlCount}
                    </span>
                  )}
                  {isActive && !collapsed && (
                    <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-brand" />
                  )}
                </>
              )}
            </NavLink>
          )
          return collapsed ? <Tooltip key={item.to} label={item.label} side="right">{link}</Tooltip> : link
        })}
      </nav>

      {/* User footer */}
      <div className="border-t border-border p-2">
        <div className={cn('flex items-center gap-2 rounded-lg p-2', !collapsed && 'bg-elevated/60')}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand/20 text-xs font-semibold text-brand-light">
            {initials(user?.full_name ?? user?.email)}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-text-primary">{user?.full_name ?? user?.email}</p>
              <p className="truncate text-[11px] text-text-muted">{user?.role ?? 'developer'}</p>
            </div>
          )}
          <Tooltip label="Sign out" side="right">
            <button
              onClick={() => void logout()}
              className={cn('rounded-md p-1.5 text-text-muted hover:bg-elevated hover:text-error', collapsed && 'ml-auto')}
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </Tooltip>
        </div>
        <button
          onClick={toggle}
          className="mt-1 flex w-full items-center justify-center rounded-lg py-1.5 text-text-muted transition-colors hover:bg-elevated hover:text-text-primary"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
        </button>
      </div>
    </aside>
  )
}
