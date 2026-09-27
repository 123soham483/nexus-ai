import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { User } from '@/types/auth'

interface AuthState {
  user: User | null
  accessToken: string | null
  refreshToken: string | null
  isAuthenticated: boolean

  setUser: (user: User) => void
  setAccessToken: (token: string) => void
  setRefreshToken: (token: string) => void
  setAuth: (user: User, accessToken: string, refreshToken: string) => void
  logout: () => void
}

/**
 * Restore the session flag synchronously from the persisted refresh token so
 * hard reloads keep the user signed in (accessToken itself stays memory-only).
 */
function restorePersistedSession(): { user: User | null; refreshToken: string | null } {
  try {
    const raw = localStorage.getItem('nexusai-auth')
    if (raw) {
      const parsed = JSON.parse(raw) as { state?: { user?: User | null; refreshToken?: string | null } }
      return { user: parsed.state?.user ?? null, refreshToken: parsed.state?.refreshToken ?? null }
    }
  } catch {
    // Ignore corrupted storage.
  }
  return { user: null, refreshToken: null }
}

/**
 * Security model: accessToken lives in memory ONLY.
 * refreshToken + user are persisted to localStorage so sessions survive reloads.
 */
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: restorePersistedSession().user,
      accessToken: null,
      refreshToken: restorePersistedSession().refreshToken,
      isAuthenticated: !!restorePersistedSession().refreshToken,

      setUser: (user) => set({ user }),
      setAccessToken: (accessToken) => set({ accessToken }),
      setRefreshToken: (refreshToken) => set({ refreshToken }),
      setAuth: (user, accessToken, refreshToken) =>
        set({ user, accessToken, refreshToken, isAuthenticated: true }),
      logout: () =>
        set({ user: null, accessToken: null, refreshToken: null, isAuthenticated: false }),
    }),
    {
      name: 'nexusai-auth',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ user: state.user, refreshToken: state.refreshToken }),
    },
  ),
)
