export interface TraceEvent {
  id: string
  task_id: string
  event_type: TraceEventType
  event_data: Record<string, unknown>
  agent_type: string | null
  timestamp: string
  sequence_number: number
}

export type TraceEventType =
  | 'task_started'
  | 'failure_patterns_checked'
  | 'routing_complete'
  | 'cost_estimated'
  | 'agent_spawned'
  | 'agent_thinking'
  | 'agent_tool_called'
  | 'agent_tool_result'
  | 'agent_memory_retrieved'
  | 'hitl_required'
  | 'hitl_resolved'
  | 'agent_completed'
  | 'hallucination_check'
  | 'quality_check'
  | 'learning_stored'
  | 'task_completed'
  | 'task_failed'
