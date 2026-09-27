from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime

_CONTEXT_MAX_DEPTH = 3
_CONTEXT_MAX_KEYS = 20
_SUSPICIOUS_CONTEXT_KEYS = frozenset(
    {"__import__", "eval", "exec", "compile", "os.system", "subprocess"}
)


def _validate_context_value(value: Any, depth: int = 0) -> None:
    if depth > _CONTEXT_MAX_DEPTH:
        raise ValueError("context exceeds maximum nesting depth")
    if isinstance(value, dict):
        if len(value) > _CONTEXT_MAX_KEYS:
            raise ValueError("context has too many keys")
        for k, v in value.items():
            if str(k).lower() in _SUSPICIOUS_CONTEXT_KEYS:
                raise ValueError(f"suspicious context key: {k}")
            _validate_context_value(v, depth + 1)
    elif isinstance(value, list):
        if len(value) > _CONTEXT_MAX_KEYS:
            raise ValueError("context list is too large")
        for item in value:
            _validate_context_value(item, depth + 1)
    elif isinstance(value, str):
        if "\x00" in value:
            raise ValueError("null bytes not allowed in context")


class TaskCreate(BaseModel):
    goal: str = Field(..., min_length=10, max_length=2000,
                     description="The goal for the agent team to accomplish")
    context: dict = Field(default={}, description="Optional extra context for agents")

    @field_validator("goal")
    @classmethod
    def clean_goal(cls, v: str) -> str:
        v = v.strip()
        if "\x00" in v:
            raise ValueError("null bytes not allowed")
        if len(v) < 10:
            raise ValueError("goal too short after stripping whitespace")
        return v

    @field_validator("context")
    @classmethod
    def validate_context(cls, v: dict) -> dict:
        _validate_context_value(v or {})
        return v or {}

class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal: str
    status: str
    estimated_cost_usd: Optional[float] = None
    actual_cost_usd: float = 0.0
    quality_score: Optional[float] = None
    agents_spawned: List[str] = []
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

class TaskDetailResponse(TaskResponse):
    result: dict = {}
    routing_decision: dict = {}
    hallucination_score: Optional[float] = None

class TaskListResponse(BaseModel):
    tasks: List[TaskResponse]
    total: int
    limit: int
    offset: int

class TraceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    event_type: str
    event_data: dict
    agent_type: Optional[str] = None
    timestamp: datetime
    sequence_number: int

class CostRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    agent_run_id: Optional[UUID] = None
    user_id: UUID
    tenant_id: UUID
    llm_model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    recorded_at: datetime

