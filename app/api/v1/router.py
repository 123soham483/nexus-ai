from fastapi import APIRouter
from app.api.v1 import auth, tasks, cost, observability, memory, agents, dispatch_health

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(cost.router, prefix="/cost", tags=["cost"])
api_router.include_router(observability.router, prefix="/observability", tags=["observability"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(dispatch_health.router, prefix="/system", tags=["system"])
