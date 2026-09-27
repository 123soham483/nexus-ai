import { create } from 'zustand'
import type { TraceEvent } from '@/types/trace'
import type { AgentRunStatus } from '@/types/agent'

interface TaskState {
  activeTaskId: string | null
  liveEvents: TraceEvent[]
  liveCost: number
  liveAgentStatuses: Record<string, AgentRunStatus>

  setActiveTask: (id: string | null) => void
  addLiveEvent: (event: TraceEvent) => void
  setLiveCost: (cost: number) => void
  updateAgentStatus: (agentType: string, status: AgentRunStatus) => void
  clearLiveState: () => void
}

export const useTaskStore = create<TaskState>()((set) => ({
  activeTaskId: null,
  liveEvents: [],
  liveCost: 0,
  liveAgentStatuses: {},

  setActiveTask: (activeTaskId) => set({ activeTaskId }),
  addLiveEvent: (event) =>
    set((state) => ({
      liveEvents: [...state.liveEvents.filter((e) => e.id !== event.id), event].slice(-400),
    })),
  setLiveCost: (liveCost) => set({ liveCost }),
  updateAgentStatus: (agentType, status) =>
    set((state) => ({ liveAgentStatuses: { ...state.liveAgentStatuses, [agentType]: status } })),
  clearLiveState: () =>
    set({ liveEvents: [], liveCost: 0, liveAgentStatuses: {}, activeTaskId: null }),
}))
