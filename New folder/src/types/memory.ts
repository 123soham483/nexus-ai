export interface MemoryResult {
  content: string
  metadata: {
    task_id?: string
    agent_type?: string
    quality_score?: number
    timestamp?: string
    failed_agent?: string
  }
  similarity_score: number
}

export interface FailurePattern {
  id: string
  goal: string
  failed_agent: string
  error: string
  stored_at: string
  similarity_score?: number
}
