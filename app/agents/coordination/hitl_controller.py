"""HitlController — non-LLM agent implementing the human-in-the-loop approval flow.

Unlike every other agent, HitlController never calls an LLM. Its ``execute``
creates a pending approval request in the :class:`~app.hitl.store.HitlStore`,
emits a ``hitl_required`` WebSocket event, waits (up to a timeout) for a human
to approve or reject it, emits ``hitl_resolved``, and returns an ``AgentResult``
reflecting the human's decision. The Tasks API resolves requests via
``POST /api/v1/tasks/{task_id}/hitl/resolve``.

The orchestrator injects its broadcaster into the created instance (the shared
factory has no broadcaster), so HITL events reach WebSocket clients. ``llm`` /
``short_term`` / ``long_term`` are accepted (and ignored) purely so the shared
``AgentFactory`` can construct it like any other agent.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.agents.base import AgentResult, BaseAgent
from app.hitl import default_store
from app.hitl.store import HitlRequest, HitlStore
from app.websockets.events import HITL_REQUIRED, HITL_RESOLVED
from app.config import settings


class HitlController(BaseAgent):
    """Concrete agent that gates a pipeline step behind human approval."""

    AGENT_TYPE = "hitl_controller"
    agent_type = "hitl_controller"

    def __init__(
        self,
        store: Optional[HitlStore] = None,
        broadcaster=None,
        *,
        agent_id: Optional[str] = None,
        llm=None,
        short_term=None,
        long_term=None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        # ``llm``/``short_term``/``long_term`` are accepted for AgentFactory
        # compatibility but never used — this agent performs no LLM call.
        super().__init__(
            llm=llm, short_term=short_term, long_term=long_term, agent_id=agent_id
        )
        self.store: HitlStore = store if store is not None else default_store
        #: Injected by the orchestrator when it runs this agent.
        self.broadcaster = broadcaster
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.HITL_TIMEOUT_SECONDS
        )

    # ── helpers ──────────────────────────────────────────────────────────────
    def _build_reason(self, goal: str, context: Dict[str, Any]) -> str:
        """Why approval is being asked — explicit ``approval_reason`` in the
        context, else a generic default."""
        return str(
            context.get("approval_reason")
            or "Human approval required before proceeding with this step"
        )

    @staticmethod
    def _request_payload(request: HitlRequest) -> dict:
        """The event/API-facing view of a request."""
        return {
            "request_id": request.id,
            "task_id": request.task_id,
            "agent_type": request.agent_type,
            "goal": request.goal,
            "reason": request.reason,
            "status": request.status,
            "resolved_by": request.resolved_by,
            "note": request.note,
            "resolved_at": (
                request.resolved_at.isoformat() if request.resolved_at else None
            ),
        }

    async def _emit_event(self, event_type: str, request: HitlRequest, task_id) -> None:
        """Emit a HITL WebSocket event (silently skipped without a broadcaster)."""
        if self.broadcaster is None:
            return
        await self.broadcaster.emit(str(task_id), event_type, self._request_payload(request))

    # ── lifecycle (fully overridden — non-LLM) ───────────────────────────────
    async def execute(self, task, context: Optional[Dict[str, Any]] = None, task_id=None) -> AgentResult:
        """Run the HITL approval flow.

        1. Create a pending request in the store
        2. Emit ``hitl_required``
        3. Wait for a human decision (or timeout)
        4. Emit ``hitl_resolved`` with the decision
        5. Return an ``AgentResult`` — success=True iff approved
        """
        goal = self._goal_from_task(task)
        context = context or {}
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        request = await self.store.create(
            task_id=task_id,
            agent_type=self.agent_type,
            goal=goal,
            reason=self._build_reason(goal, context),
            timeout_seconds=self.timeout_seconds,
        )

        await self._emit_event(HITL_REQUIRED, request, task_id)

        resolved = await self.store.wait_for(request.id, timeout=self.timeout_seconds)

        approved = resolved.status == "approved"
        error = None
        if not approved:
            error = (
                "Approval rejected by human"
                if resolved.status == "rejected"
                else f"Approval timed out after {self.timeout_seconds}s"
            )

        parsed: dict = {
            "request_id": request.id,
            "decision": resolved.status,
            "approved": approved,
            "reason": request.reason,
            "resolved_by": resolved.resolved_by,
            "note": resolved.note,
        }

        completed_at = datetime.now(timezone.utc)
        result = AgentResult(
            agent_type=self.agent_type,
            agent_id=self.agent_id,
            provider="human",
            model="human-in-the-loop",
            system_prompt="",  # no LLM prompt is built
            user_prompt=goal,
            content=json.dumps(parsed, default=str),
            parsed=parsed,
            reasoning=request.reason,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            status=resolved.status,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=time.perf_counter() - t0,
            success=approved,
            error=error,
            task_id=task_id,
            confidence_score=1.0 if approved else 0.0,
        )

        await self._emit_event(HITL_RESOLVED, resolved, task_id)

        return result
