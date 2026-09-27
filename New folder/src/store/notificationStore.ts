import { create } from 'zustand'

export interface AppNotification {
  id: string
  kind: 'hitl' | 'task' | 'budget' | 'system'
  title: string
  body?: string
  createdAt: string
  read: boolean
}

interface NotificationState {
  hitlPendingCount: number
  notifications: AppNotification[]
  lastToastAt: Record<string, number>

  setHitlPendingCount: (count: number) => void
  push: (n: Omit<AppNotification, 'id' | 'createdAt' | 'read'>) => void
  markAllRead: () => void
  clear: () => void
}

/** Dedupe toasts per key so repeated WS events don't spam. */
const TOAST_COOLDOWN_MS = 30_000

export const useNotificationStore = create<NotificationState>()((set, get) => ({
  hitlPendingCount: 0,
  notifications: [],
  lastToastAt: {},

  setHitlPendingCount: (hitlPendingCount) => set({ hitlPendingCount }),

  push: (n) => {
    const now = Date.now()
    const key = `${n.kind}:${n.title}`
    if (now - (get().lastToastAt[key] ?? 0) < TOAST_COOLDOWN_MS) return
    set((state) => ({
      lastToastAt: { ...state.lastToastAt, [key]: now },
      notifications: [
        { ...n, id: `n-${now}-${Math.random().toString(36).slice(2, 7)}`, createdAt: new Date().toISOString(), read: false },
        ...state.notifications,
      ].slice(0, 50),
    }))
  },

  markAllRead: () =>
    set((state) => ({ notifications: state.notifications.map((n) => ({ ...n, read: true })) })),
  clear: () => set({ notifications: [] }),
}))
