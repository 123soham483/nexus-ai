import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Plus, ListTodo, Wallet, Bot, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useNotificationStore } from '@/store/notificationStore'

const ITEMS: Array<{ to: string; label: string; icon: LucideIcon }> = [
  { to: '/dashboard', label: 'Home', icon: LayoutDashboard },
  { to: '/tasks/new', label: 'New', icon: Plus },
  { to: '/tasks', label: 'Tasks', icon: ListTodo },
  { to: '/cost', label: 'Cost', icon: Wallet },
  { to: '/agents', label: 'Agents', icon: Bot },
]

export function MobileNav() {
  const hitlCount = useNotificationStore((s) => s.hitlPendingCount)
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-surface/95 backdrop-blur md:hidden">
      {ITEMS.map((item) => {
        const Icon = item.icon
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/dashboard' || item.to === '/tasks'}
            className={({ isActive }) =>
              cn(
                'relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium',
                isActive ? 'text-brand-light' : 'text-text-muted',
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon className="h-5 w-5" />
                <span>{item.label}</span>
                {isActive && <span className="absolute top-0 h-0.5 w-8 rounded-full bg-brand" />}
                {item.to === '/tasks' && hitlCount > 0 && (
                  <span className="absolute right-[calc(50%-18px)] top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-error px-0.5 text-[9px] font-bold text-white">
                    {hitlCount}
                  </span>
                )}
              </>
            )}
          </NavLink>
        )
      })}
    </nav>
  )
}
