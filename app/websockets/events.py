# All WebSocket event type strings used across the system
TASK_STARTED              = "task_started"
FAILURE_PATTERNS_CHECKED  = "failure_patterns_checked"
ROUTING_COMPLETE          = "routing_complete"
COST_ESTIMATED            = "cost_estimated"
AGENT_SPAWNED             = "agent_spawned"
AGENT_THINKING            = "agent_thinking"
AGENT_TOOL_CALLED         = "agent_tool_called"
AGENT_TOOL_RESULT         = "agent_tool_result"
AGENT_MEMORY_RETRIEVED    = "agent_memory_retrieved"
HITL_REQUIRED             = "hitl_required"
HITL_RESOLVED             = "hitl_resolved"
AGENT_COMPLETED           = "agent_completed"
AGENT_ERROR               = "agent_error"
HALLUCINATION_CHECK       = "hallucination_check"
QUALITY_CHECK             = "quality_check"
LEARNING_STORED           = "learning_stored"
TASK_COMPLETED            = "task_completed"
TASK_FAILED               = "task_failed"

ALL_EVENT_TYPES = {
    TASK_STARTED, FAILURE_PATTERNS_CHECKED, ROUTING_COMPLETE,
    COST_ESTIMATED, AGENT_SPAWNED, AGENT_THINKING, AGENT_TOOL_CALLED,
    AGENT_TOOL_RESULT, AGENT_MEMORY_RETRIEVED, HITL_REQUIRED,
    HITL_RESOLVED, AGENT_COMPLETED, AGENT_ERROR, HALLUCINATION_CHECK,
    QUALITY_CHECK, LEARNING_STORED, TASK_COMPLETED, TASK_FAILED,
}
