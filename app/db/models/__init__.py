"""Model package.

Importing this package registers every model on ``Base.metadata`` so that
``create_all`` (tests) and Alembic autogenerate (Postgres) see the full schema.
"""
from app.db.base import Base
from app.db.models.enums import TaskStatus
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.task import Task
from app.db.models.agent_run import AgentRun
from app.db.models.trace import Trace
from app.db.models.cost_record import CostRecord
from app.db.models.hallucination_score import HallucinationScoreRecord

__all__ = [
    "Base",
    "TaskStatus",
    "Tenant",
    "User",
    "Task",
    "AgentRun",
    "Trace",
    "CostRecord",
    "HallucinationScoreRecord",
]
