import { Navigate, Outlet } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { MobileNav } from '@/components/layout/MobileNav'
import { ConnectionBanner } from '@/components/layout/ConnectionBanner'
import { HitlSync } from '@/components/layout/HitlSync'
import { useAuthStore } from '@/store/authStore'
import { useUIStore } from '@/store/uiStore'
import { cn } from '@/lib/utils'

export function ProtectedLayout() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const collapsed = useUIStore((s) => s.sidebarCollapsed)

  if (!isAuthenticated) return <Navigate to="/login" replace />

  return (
    <div className="min-h-screen">
      <HitlSync />
      <Sidebar />
      <div
        className={cn(
          'flex min-h-screen flex-col transition-[margin] duration-200',
          collapsed ? 'md:ml-16' : 'md:ml-60',
        )}
      >
        <TopBar />
        <ConnectionBanner />
        <Outlet />
      </div>
      <MobileNav />
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: 'var(--bg-elevated)',
            color: 'var(--text-primary)',
            border: '1px solid var(--bg-border)',
            fontSize: '13px',
          },
        }}
      />
    </div>
  )
}
