import { create } from 'zustand'

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'disconnected'

interface ConnectionState {
  status: ConnectionStatus
  taskIds: string[]
  setStatus: (status: ConnectionStatus) => void
  register: (taskId: string) => void
  unregister: (taskId: string) => void
}

export const useConnectionStore = create<ConnectionState>()((set) => ({
  status: 'disconnected',
  taskIds: [],
  setStatus: (status) => set({ status }),
  register: (taskId) =>
    set((s) => ({ taskIds: s.taskIds.includes(taskId) ? s.taskIds : [...s.taskIds, taskId] })),
  unregister: (taskId) => set((s) => ({ taskIds: s.taskIds.filter((t) => t !== taskId) })),
}))
