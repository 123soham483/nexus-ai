import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function PageWrapper({ children, className, maxWidth = 'max-w-7xl' }: { children: ReactNode; className?: string; maxWidth?: string }) {
  return (
    <main className={cn('mx-auto w-full flex-1 px-4 py-5 sm:px-6 lg:px-8', maxWidth, className)}>
      {children}
    </main>
  )
}
