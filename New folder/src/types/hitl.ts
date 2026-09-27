export interface HITLApproval {
  approval_id: string
  task_id: string
  tool_name: string
  tool_description: string
  tool_params: Record<string, unknown>
  agent_type: string
  timeout_seconds: number
  created_at: string
  expires_at: string
}

export type HITLDecision = 'approved' | 'rejected'

export interface HITLHistoryEntry {
  approval_id: string
  task_id: string
  goal: string
  tool_name: string
  agent_type: string
  decision: HITLDecision
  decided_at: string
}
