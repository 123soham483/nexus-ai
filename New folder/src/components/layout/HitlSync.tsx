import { usePendingApprovals } from '@/hooks/useHITL'

/** Keeps the sidebar/topbar HITL badges in sync app-wide. */
export function HitlSync() {
  usePendingApprovals()
  return null
}
