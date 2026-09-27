"""Optional demo: repeated similar goals show routing confidence shifting (Phase 3 cleanup).

Does not modify production code paths — run manually against a dev stack with Redis.
"""
from __future__ import annotations

import asyncio
import os

# Example usage:
#   PYTHONPATH=. python scripts/learning_routing_demo.py


async def main() -> None:
    from app.core.router import TaskRouter
    from app.memory.learning_engine import LearningEngine
    from app.memory.long_term import LongTermMemory

    goal = "implement a REST API with authentication in Python"
    tenant_id = os.environ.get("DEMO_TENANT_ID", "00000000-0000-0000-0000-000000000001")

    router = TaskRouter()
    engine = LearningEngine(LongTermMemory(tenant_prefix="demo"))

    for i in range(5):
        plan = await router.plan(goal, {}, [], tenant_id=tenant_id)
        print(f"run {i + 1}: agents={plan.agents} confidence={plan.confidence:.2f}")
        await engine.update_routing_confidence(goal, plan.agents, 0.95, tenant_id)


if __name__ == "__main__":
    asyncio.run(main())
