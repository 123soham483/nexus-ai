"""Orchestrator — the main engine of NexusAI that coordinates the execution pipeline."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent
from app.config import settings
from app.db.models.task import Task
from app.db.models.enums import TaskStatus
from app.db.models.cost_record import CostRecord
from app.llm.routing import estimate_agent_cost
from app.observability.hallucination_scorer import HallucinationScorer
from app.observability.metrics import record_task_completed, record_task_started
from app.observability.tracer import (
    TASK_STATUS as TASK_STATUS_ATTR,
    NexusTracer,
    get_tracer,
)

logger = logging.getLogger(__name__)

#: Agents that are never "content" agents and so are excluded from the
#: hallucination retry sweep (they validate, gate, or cost-account rather than
#: produce the content a hallucination check applies to).
_NON_CONTENT_AGENTS = frozenset(
    {"validator", "hallucination_detector", "cost_controller", "hitl_controller"}
)
#: How many times a failed content agent may be retried after a low
#: hallucination score (Phase 3, Step 3.2).
_MAX_HALLUCINATION_RETRIES = 2


def _accepts_kwarg(fn: Callable[..., Any], name: str) -> bool:
    """Whether ``fn`` can be called with keyword argument ``name``.

    Lets the orchestrator forward tenant context to routers that understand it
    (the real ``TaskRouter``, which uses it for tenant-scoped learned hints)
    while leaving older/simpler routers — including test fakes — callable with
    their original signature.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins/C-callables
        return False
    if name in params:
        return True
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )


class ExecutableAgent(Protocol):
    """Contract for agents the orchestrator runs.

    Concrete agents implement ``execute()``; the abstract :class:`BaseAgent`
    itself only defines ``run``, so this protocol is what the factory returns.
    """

    agent_type: str

    async def execute(self, task: str, context: dict, task_id: str) -> AgentResult: ...


class Orchestrator:
    """Coordinates task execution: routing -> agent execution -> validation -> DB persistence."""

    def __init__(
        self,
        router,  # TaskRouter
        agent_factory: Callable[[str], ExecutableAgent],
        short_memory,  # ShortTermMemory
        long_memory,  # LongTermMemory
        broadcaster,  # WebSocketBroadcaster
        db_session=None,  # AsyncSession
        learning_engine=None,  # LearningEngine (Phase 3; optional)
        learning_causal_inline: bool = False,
        tracer: Optional[NexusTracer] = None,
    ) -> None:
        self.router = router
        self.agent_factory = agent_factory
        self.short_memory = short_memory
        self.long_memory = long_memory
        self.broadcaster = broadcaster
        self.db_session = db_session
        #: Phase 3 self-learning. Explicitly injected (the Celery worker wires a
        #: real one); when absent the orchestrator keeps the Phase 2 behaviour of
        #: a plain ``store_task_result`` / ``store_failure``. Keeping learning
        #: opt-in means unit tests that don't care about it stay unaffected.
        self.learning_engine = learning_engine
        #: When True the Level-2 causal analysis is awaited inline (deterministic
        #: tests); when False it is fire-and-forget so it never delays the task.
        self.learning_causal_inline = learning_causal_inline
        #: Phase 4 tracing: the task span is the ROOT of a trace, with agent and
        #: LLM spans nested underneath it automatically.
        self.tracer = tracer if tracer is not None else get_tracer()
        #: Whether ``router.plan`` accepts a ``tenant_id`` kwarg (Phase 3 learned
        #: routing hints are tenant-scoped). Resolved once so the hot path stays
        #: cheap and simple routers stay supported.
        self._router_takes_tenant = _accepts_kwarg(self.router.plan, "tenant_id")
        self._db_lock = asyncio.Lock()

    async def execute_task(
        self,
        task_id: str,
        goal: str,
        context: dict,
        tenant_id: str,
        user_id: str,
    ) -> dict:
        """Full execution pipeline, wrapped in the root trace span (Step 4.1)."""
        with self.tracer.task_span(
            task_id=str(task_id), goal=goal, tenant_id=str(tenant_id)
        ) as span:
            try:
                result = await self._execute_task_inner(
                    span, task_id, goal, context, tenant_id, user_id
                )
            except Exception:
                span.set_attribute(TASK_STATUS_ATTR, "failed")
                raise
            span.set_attribute(TASK_STATUS_ATTR, "completed")
            return result

    async def _execute_task_inner(
        self,
        span,
        task_id: str,
        goal: str,
        context: dict,
        tenant_id: str,
        user_id: str,
    ) -> dict:
        """The pipeline body. ``span`` is the root task span (may be a no-op)."""
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        import uuid as _uuid_module
        uuid_task_id = (
            _uuid_module.UUID(task_id) if isinstance(task_id, str) else task_id
        )

        # Helper to retrieve Task row
        async def _get_task_row():
            if self.db_session:
                result = await self.db_session.execute(
                    select(Task).where(Task.id == uuid_task_id)
                )
                return result.scalar_one_or_none()
            return None

        try:
            # 1. Update Task.status = "routing" in DB
            task = await _get_task_row()
            if task:
                task.status = TaskStatus.ROUTING
                task.started_at = started_at
                await self.db_session.flush()
                # Commit the transition IMMEDIATELY so users see progress in the
                # UI. Without this, the row stays committed-PENDING for the whole
                # (possibly minutes-long) LLM phase — which reads as "task stuck
                # on pending" (BRAIN.md bug T8).
                await self.db_session.commit()

            # 2. Emit: "task_started"
            await self._emit("task_started", {"goal": goal, "task_id": str(task_id)}, str(task_id))
            record_task_started(str(tenant_id))

            # 3. Search failure store. Memory is a READ-ONLY side input to
            #    routing: a broken embedder/Chroma must degrade to "no history"
            #    instead of masking the real task error (BRAIN.md T5 — the
            #    live E2E failed with "No module named 'sentence_transformers'",
            #    hiding the actual LLM failure from the task result).
            try:
                failures = await self.long_memory.search_similar_failures(goal, n_results=3)
            except Exception as mem_exc:
                logger.warning("failure-store read degraded to empty: %s", mem_exc)
                failures = []

            # 4. Emit: "failure_patterns_checked"
            await self._emit("failure_patterns_checked", {"count": len(failures)}, str(task_id))

            # 5. Get routing plan (forward tenant_id when the router supports it
            #    so learned routing hints stay tenant-scoped).
            plan = await self.router.plan(
                goal,
                context,
                [
                    {"error": f.content, "failed_agent": f.metadata.get("failed_agent", "")}
                    for f in failures
                ],
                **({"tenant_id": str(tenant_id)} if self._router_takes_tenant else {}),
            )

            # 6. Update Task.routing_decision in DB
            task = await _get_task_row()
            plan_dict = {
                "agents": plan.agents,
                "sequential": plan.sequential,
                "parallel_groups": plan.parallel_groups,
                "reasoning": plan.reasoning,
                "confidence": plan.confidence,
                "estimated_tokens": plan.estimated_tokens,
            }
            if task:
                task.routing_decision = plan_dict
                task.agents_spawned = plan.agents
                await self.db_session.flush()

            span.set_attributes(
                {
                    "nexus.routing.agents": ",".join(plan.agents),
                    "nexus.routing.confidence": float(plan.confidence),
                }
            )

            # 7. Emit: "routing_complete"
            await self._emit("routing_complete", {
                "agents": plan.agents,
                "reasoning": plan.reasoning,
                "confidence": plan.confidence,
            }, str(task_id))

            # 8. Estimate total cost
            total_est = 0.0
            for agent_type in plan.agents:
                total_est += estimate_agent_cost(
                    agent_type, plan.estimated_tokens.get(agent_type, 1000)
                )

            # 9. Update Task.estimated_cost_usd in DB
            task = await _get_task_row()
            if task:
                task.estimated_cost_usd = total_est
                await self.db_session.flush()

            # 10. Emit: "cost_estimated"
            await self._emit("cost_estimated", {"estimated_usd": total_est}, str(task_id))
            span.set_attribute("nexus.routing.estimated_cost_usd", float(total_est))

            # 11. Store context in short-term memory
            await self.short_memory.set_value(task_id, "goal", goal)
            await self.short_memory.set_value(task_id, "context", json.dumps(context))

            # 12. Update Task.status = "running" in DB
            task = await _get_task_row()
            if task:
                task.status = TaskStatus.RUNNING
                await self.db_session.flush()
                await self.db_session.commit()

            # 13. Execute agents per routing plan
            all_results: List[AgentResult] = []

            # Sequential agents
            for agent_type in plan.sequential:
                result = await self._run_single_agent(
                    agent_type, goal, context, str(task_id), tenant_id, user_id
                )
                all_results.append(result)
                await self.short_memory.set_value(
                    task_id,
                    f"result:{agent_type}",
                    {"output": result.output, "success": result.success}
                )

            # Parallel groups
            for group in plan.parallel_groups:
                group_results = await asyncio.gather(
                    *[
                        self._run_single_agent(
                            a, goal, context, str(task_id), tenant_id, user_id
                        )
                        for a in group
                    ],
                    return_exceptions=True
                )
                for r in group_results:
                    if isinstance(r, BaseException):
                        await self._emit("agent_error", {"error": str(r)}, str(task_id))
                    else:
                        all_results.append(r)

            # 14. Build final result from all_results
            last_agent_output = ""
            if all_results:
                last_res = all_results[-1]
                if isinstance(last_res.output, dict):
                    last_agent_output = last_res.output.get("code") or last_res.output.get("explanation") or last_res.content
                else:
                    last_agent_output = str(last_res.output)
            
            final_result = {
                "summary": last_agent_output,
                "outputs": {r.agent_type: r.output for r in all_results},
            }

            # 15. Calculate aggregate quality score (avg of confidence_scores)
            quality_score = 1.0
            if all_results:
                quality_score = sum(r.confidence_score for r in all_results) / len(all_results)

            # 16. Calculate total actual cost (sum of cost_usd)
            total_actual_cost = sum(r.cost_usd for r in all_results)
            total_tokens = sum(r.input_tokens + r.output_tokens for r in all_results)

            # 17. Emit: "quality_check"
            await self._emit("quality_check", {"score": quality_score, "passed": quality_score >= 0.7}, str(task_id))

            # 18. Emit: "hallucination_check" — the REAL detector score when the
            #     detector ran (Phase 3 fixed the hardcoded 0.95 placeholder).
            hallucination_score, hallucination_passed = self._hallucination_result(
                all_results
            )
            await self._emit(
                "hallucination_check",
                {"score": hallucination_score, "passed": hallucination_passed},
                str(task_id),
            )
            if self.db_session is not None:
                try:
                    scorer = HallucinationScorer(db_session=self.db_session)
                    await scorer.record_score(
                        str(task_id),
                        "hallucination_detector",
                        float(hallucination_score),
                        "pass" if hallucination_passed else "fail",
                        str(tenant_id),
                    )
                except Exception as score_exc:
                    logger.warning("HallucinationScorer.record_score failed: %s", score_exc)
            span.set_attributes(
                {
                    "nexus.quality.score": float(quality_score),
                    "nexus.hallucination.score": float(hallucination_score),
                    "nexus.hallucination.passed": bool(hallucination_passed),
                }
            )

            # 18b. Low-confidence output → retry the failed content agents (max 2).
            detector_ran = any(
                r.agent_type == "hallucination_detector" for r in all_results
            )
            if detector_ran and not hallucination_passed:
                retried = await self._retry_failed_agents(
                    all_results, plan, goal, context, str(task_id), tenant_id, user_id
                )
                if retried:
                    all_results.extend(retried)
                    quality_score = (
                        sum(r.confidence_score for r in all_results) / len(all_results)
                    )
                    total_actual_cost = sum(r.cost_usd for r in all_results)
                    total_tokens = sum(
                        r.input_tokens + r.output_tokens for r in all_results
                    )

            # 19-20. Learn from this success.
            if self.learning_engine is not None:
                await self._learn_from_success_safe(
                    task_id, goal, all_results, plan,
                    total_actual_cost, quality_score, tenant_id,
                )
            else:
                # 19. Store success in long-term memory (Phase 2 path)
                await self.long_memory.store_task_result(
                    task_id=task_id,
                    goal=goal,
                    result_summary=final_result.get("summary", ""),
                    agent_types_used=plan.agents,
                    cost_usd=total_actual_cost,
                    quality_score=quality_score,
                )

                # 20. Emit: "learning_stored"
                await self._emit("learning_stored", {"pattern_type": "task_success"}, str(task_id))

            # 21. Update Task in DB
            completed_at = datetime.now(timezone.utc)
            duration_seconds = time.perf_counter() - t0
            task = await _get_task_row()
            if task:
                task.status = TaskStatus.COMPLETED
                task.result = final_result
                task.quality_score = quality_score
                task.actual_cost_usd = total_actual_cost
                task.tokens_used = total_tokens
                task.completed_at = completed_at
                task.duration_seconds = duration_seconds
                task.llm_calls_count = len(all_results)
                # Phase 4 (Step 4.3): persist the REAL hallucination score on the
                # task so tenant averaging and trend queries read one source.
                task.hallucination_score = float(hallucination_score)
                await self.db_session.flush()

            span.set_attributes(
                {
                    "nexus.task.actual_cost_usd": float(total_actual_cost),
                    "nexus.task.tokens_used": int(total_tokens),
                    "nexus.task.agent_runs": len(all_results),
                    "nexus.task.duration_seconds": float(duration_seconds),
                }
            )

            # 22. Emit: "task_completed"
            await self._emit("task_completed", {
                "success": True,
                "total_cost": total_actual_cost,
                "duration": duration_seconds,
            }, str(task_id))

            record_task_completed(str(tenant_id), float(duration_seconds), "completed")

            # 23. Return final_result dict
            return final_result

        except Exception as exc:
            # ON ANY EXCEPTION
            if self.learning_engine is not None:
                try:
                    await self.learning_engine.learn_from_failure(
                        task_id, goal, str(exc), "orchestrator", str(tenant_id)
                    )
                except Exception as learn_exc:  # learning must never mask the real error
                    logger.warning("learn_from_failure failed: %s", learn_exc)
            else:
                try:
                    await self.long_memory.store_failure(task_id, goal, str(exc), "orchestrator")
                except Exception:
                    pass

            # Emit FIRST so the task_failed trace lands in the same session,
            # then persist. The worker's ``get_session_context`` rolls back
            # uncommitted work on exception, so a bare flush() here used to be
            # discarded — leaving the task in `pending` forever even though the
            # failure path had "run" (BRAIN.md bug T2).
            await self._emit("task_failed", {"error": str(exc)}, str(task_id))

            task = await _get_task_row()
            if task:
                task.status = TaskStatus.FAILED
                task.result = {"error": str(exc)}
                task.completed_at = datetime.now(timezone.utc)
                task.duration_seconds = time.perf_counter() - t0
                await self.db_session.flush()
                # Commit NOW, while the exception is still propagating: status,
                # error and every trace emitted in this block become durable.
                try:
                    await self.db_session.commit()
                except Exception as commit_exc:  # pragma: no cover - defensive
                    logger.warning(
                        "failure-state commit failed for task %s: %s",
                        task_id,
                        commit_exc,
                    )

            record_task_completed(
                str(tenant_id), float(time.perf_counter() - t0), "failed"
            )
            raise exc

    # ── Phase 3 helpers ──────────────────────────────────────────────────────
    async def _learn_from_success_safe(
        self,
        task_id,
        goal: str,
        all_results: List[AgentResult],
        plan,
        cost: float,
        quality: float,
        tenant_id: str,
    ) -> None:
        """Run the three learning levels, swallowing every failure (Phase 3).

        Learning is a *side effect* of a successful task: a broken store, LLM or
        Redis must never turn a completed task into a failed one (BRAIN.md:
        "learning must never crash a task"). Levels 1 and 3 are awaited so the
        Level-1 pattern is durable before the task is marked COMPLETED; Level 2
        runs inline only in deterministic tests, otherwise fire-and-forget.
        """
        if self.learning_engine is None:
            return
        try:
            # Level 1 — storage with rich structural metadata.
            await self.learning_engine.store_success(
                task_id, goal, all_results, plan, cost, quality, str(tenant_id)
            )
        except Exception as exc:
            logger.warning("LearningEngine.store_success failed: %s", exc)

        if self.learning_causal_inline:
            await self._analyze_why_safe(task_id, goal, all_results, tenant_id)
        else:
            asyncio.ensure_future(
                self._analyze_why_safe(task_id, goal, all_results, tenant_id)
            )

        try:
            # Level 3 — nudge the routing-confidence counters.
            await self.learning_engine.update_routing_confidence(
                goal, plan.agents, quality, str(tenant_id)
            )
        except Exception as exc:
            logger.warning("LearningEngine.update_routing_confidence failed: %s", exc)

        await self._emit("learning_stored", {
            "pattern_type": "task_success",
            "levels": ["storage", "causal", "routing_confidence"],
        }, str(task_id))

    @staticmethod
    def _hallucination_result(all_results: List[AgentResult]) -> tuple[float, bool]:
        """Real hallucination score from the detector's AgentResult, if it ran.

        Reads the detector's parsed ``score`` (falling back to its confidence
        score). When the detector did not run, returns a passing neutral score —
        absence of a check is not evidence of a hallucination.
        """
        for result in all_results:
            if result.agent_type != "hallucination_detector":
                continue
            parsed = result.parsed or {}
            score: Optional[float] = None
            if isinstance(parsed, dict):
                for key in ("score", "hallucination_score", "confidence"):
                    if parsed.get(key) is not None:
                        try:
                            score = float(parsed[key])
                            break
                        except (TypeError, ValueError):
                            continue
            if score is None:
                score = float(result.confidence_score)
            # Scores may be "confidence in correctness" or "hallucination risk"
            # depending on the prompt; the detector emits a 0-1 score where
            # higher is healthier, so use it directly.
            score = max(0.0, min(1.0, score))
            return score, score >= settings.HALLUCINATION_SCORE_THRESHOLD
        return 1.0, True

    async def _retry_failed_agents(
        self,
        all_results: List[AgentResult],
        plan,
        goal: str,
        context: dict,
        task_id: str,
        tenant_id: str,
        user_id: str,
    ) -> List[AgentResult]:
        """Re-run content agents that failed, up to ``_MAX_HALLUCINATION_RETRIES``.

        Only agents that actually failed (``success`` is False) and are not
        validators/gates are retried. Each retry attempt emits the normal agent
        events and persists its AgentRun, so the retry is fully observable.
        """
        failed_types = [
            r.agent_type
            for r in all_results
            if not r.success and r.agent_type not in _NON_CONTENT_AGENTS
        ]
        if not failed_types:
            return []

        retried: List[AgentResult] = []
        for attempt in range(_MAX_HALLUCINATION_RETRIES):
            await self._emit(
                "hallucination_retry",
                {"attempt": attempt + 1, "agents": list(set(failed_types))},
                task_id,
            )
            attempt_results = []
            for agent_type in failed_types:
                try:
                    attempt_results.append(
                        await self._run_single_agent(
                            agent_type, goal, context, task_id, tenant_id, user_id
                        )
                    )
                except Exception as retry_exc:
                    await self._emit(
                        "agent_error", {"error": str(retry_exc)}, task_id
                    )
            retried.extend(attempt_results)
            if any(r.success for r in attempt_results):
                break
        return retried

    async def _analyze_why_safe(
        self, task_id, goal: str, all_results: List[AgentResult], tenant_id
    ) -> None:
        """Run the Level-2 causal analysis, swallowing every failure."""
        if self.learning_engine is None:
            return
        try:
            await self.learning_engine.analyze_why(
                task_id, goal, all_results, str(tenant_id)
            )
        except Exception as exc:  # background task — log, never propagate
            logger.warning("analyze_why failed: %s", exc)

    async def _run_single_agent(
        self,
        agent_type: str,
        goal: str,
        context: dict,
        task_id: str,
        tenant_id: str,
        user_id: str,
    ) -> AgentResult:
        await self._emit("agent_spawned", {"agent_type": agent_type}, task_id)
        agent = self.agent_factory(agent_type)
        # HitlController is created by the shared factory without a broadcaster;
        # inject the orchestrator's so hitl_required/hitl_resolved events reach
        # WebSocket clients. Other agents don't declare ``broadcaster`` — no-op.
        if hasattr(agent, "broadcaster") and agent.broadcaster is None:
            agent.broadcaster = self.broadcaster
        result = await agent.execute(goal, context, task_id)

        # Persist AgentRun + CostRecord rows in DB
        if self.db_session:
            async with self._db_lock:
                import uuid as _uuid_module
                db_task_id = (
                    _uuid_module.UUID(task_id) if isinstance(task_id, str) else task_id
                )
                agent_run = result.to_agent_run(db_task_id)
                self.db_session.add(agent_run)
                await self.db_session.flush()  # populates agent_run.id

                # Coerce to UUIDs for the FK columns (the Celery worker passes
                # strings; callers may pass UUID objects). ``Any`` is deliberate:
                # the defensive branch must stay permissive at runtime.
                user_uuid: Any = (
                    _uuid_module.UUID(user_id) if isinstance(user_id, str) else user_id
                )
                tenant_uuid: Any = (
                    _uuid_module.UUID(tenant_id)
                    if isinstance(tenant_id, str)
                    else tenant_id
                )
                cost_record = CostRecord(
                    task_id=db_task_id,
                    agent_run_id=agent_run.id,
                    user_id=user_uuid,
                    tenant_id=tenant_uuid,
                    llm_model=result.model_used or result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd,
                )
                self.db_session.add(cost_record)
                await self.db_session.flush()

        await self._emit("agent_completed", {
            "agent_type": agent_type,
            "success": result.success,
            "cost_usd": result.cost_usd,
            "duration_seconds": result.duration_seconds,
        }, task_id)

        return result

    async def _emit(self, event_type: str, data: dict, task_id: str) -> None:
        if self.broadcaster:
            await self.broadcaster.emit(task_id, event_type, data)


def default_agent_factory(agent_type: str) -> ExecutableAgent:
    """Default factory mapping agent_type -> concrete agent instances.

    Thin wrapper over the shared :class:`app.agents.factory.AgentFactory`
    registry (no injected providers — agents use their own defaults).
    """
    from app.agents.factory import default_factory

    return default_factory.create(agent_type)
