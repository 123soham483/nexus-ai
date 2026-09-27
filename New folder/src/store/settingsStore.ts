import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { Currency } from '@/lib/utils'

export interface BudgetAlertPrefs {
  alertAt70: boolean
  alertAt90: boolean
  hardStopAt100: boolean
}

export interface NotificationPrefs {
  taskCompleted: boolean
  taskFailed: boolean
  hitlRequired: boolean
  budgetAlert70: boolean
  budgetAlert90: boolean
  weeklyReport: boolean
}

interface SettingsState {
  currency: Currency
  monthlyBudgetUsd: number
  budgetAlerts: BudgetAlertPrefs
  notifications: NotificationPrefs

  setCurrency: (currency: Currency) => void
  setMonthlyBudget: (monthlyBudgetUsd: number) => void
  setBudgetAlerts: (prefs: Partial<BudgetAlertPrefs>) => void
  setNotifications: (prefs: Partial<NotificationPrefs>) => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      currency: 'INR',
      monthlyBudgetUsd: 60.24, // ≈ ₹5,000 display
      budgetAlerts: { alertAt70: true, alertAt90: true, hardStopAt100: false },
      notifications: {
        taskCompleted: true,
        taskFailed: true,
        hitlRequired: true,
        budgetAlert70: true,
        budgetAlert90: true,
        weeklyReport: false,
      },

      setCurrency: (currency) => set({ currency }),
      setMonthlyBudget: (monthlyBudgetUsd) => set({ monthlyBudgetUsd }),
      setBudgetAlerts: (budgetAlerts) =>
        set((state) => ({ budgetAlerts: { ...state.budgetAlerts, ...budgetAlerts } })),
      setNotifications: (notifications) =>
        set((state) => ({ notifications: { ...state.notifications, ...notifications } })),
    }),
    {
      name: 'nexusai-settings',
      storage: createJSONStorage(() => localStorage),
    },
  ),
)
