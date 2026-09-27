"""LearningEngine — 3-level self-learning after every task (Phase 3, Step 3.1).

NexusAI gets smarter with every run. After a task completes (or fails) the
orchestrator hands the outcome to this engine, which learns at three levels:

    Level 1 — storage:      the task result is stored in the tenant's ``_tasks``
                            collection with *rich* metadata (which agents ran,
                            how they were grouped, routing confidence, cost,
                            quality) so future searches retrieve not just "what
                            worked" but "how it was structured".
    Level 2 — causal:       an LLM (Gemini — the project's live provider)
                            explains WHY the routing worked, extracting a
                            reusable ``goal_pattern`` and the ``risk_factors``
                            to watch for. Stored in the ``_patterns`` collection.
    Level 3 — routing:      keyword → agent confidence counters in Redis. These
                            feed ``TaskRouter.plan`` (Step 3.2) so routing is
                            biased toward what has actually worked for similar
                            goals in the past.

Design rules (BRAIN.md): every collaborator is injectable (long-term memory,
LLM provider, Redis) so the whole engine is unit-tested with fakes; learning
must NEVER crash a task — every level degrades gracefully (a failed LLM call or
an unreachable Redis logs and returns rather than raising).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.llm import LLMMessage, LLMProvider, default_provider

logger = logging.getLogger(__name__)

#: Redis key for one learned (tenant, keyword, agent) routing confidence score.
CONFIDENCE_KEY_TEMPLATE = "routing:confidence:{tenant}:{keyword}:{agent}"
#: Rolling window for the learned scores (30 days).
ROUTING_TTL_SECONDS = 30 * 24 * 3600
#: Quality above this bumps the confidence by :data:`STRONG_SIGNAL` instead of 1.
STRONG_QUALITY = 0.8
#: Quality below this DECREMENTS the confidence (negative signal).
WEAK_QUALITY = 0.5
STRONG_SIGNAL = 2

#: Words too common to carry routing signal. Kept small and readable on purpose.
STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have how i if in into is it its me my
    of on or our so that the their them then there these this to up us was we
    were what when where which who why will with you your write writing make
    made build building create creating using use used get got please can could
    would should do does did new also need needs want wants add added via per
    code file files task goal
    """.split()
)

_ANALYSIS_SYSTEM_PROMPT = (
    "You are an AI system analyst. Analyze why this task succeeded."
)

_ANALYSIS_USER_TEMPLATE = """Goal: {goal}
Agents used: {agent_types}
Quality score: {quality}
Agent confidence scores: {confidence_per_agent}

Answer these questions concisely:
1. WHY did this agent selection work for this goal type?
2. What pattern in the goal text maps to these agent types?
3. What would fail this task next time to watch out for?

Return JSON only:
{{
  "why_it_worked": "...",
  "goal_pattern": "...",
  "risk_factors": ["...", "..."]
}}
"""

_FAILURE_SYSTEM_PROMPT = (
    "You are an AI system analyst. Analyze why this task failed."
)

_FAILURE_USER_TEMPLATE = """Goal: {goal}
Failed agent: {failed_agent}
Error: {error}

Answer these questions concisely:
1. WHY did this agent fail for this goal type?
2. What pattern in the goal text triggered this failure?
3. What should the router do differently next time?

Return JSON only:
{{
  "why_it_failed": "...",
  "goal_pattern": "...",
  "risk_factors": ["...", "..."]
}}
"""


def extract_keywords(goal: str) -> List[str]:
    """Lowercased, punctuation-stripped, de-duplicated, stopword-filtered terms.

    Order is preserved (first occurrence wins) so the counters and hints are
    deterministic and easy to reason about in tests.
    """
    if not goal:
        return []
    tokens = re.split(r"[^a-z0-9]+", goal.lower())
    seen: set[str] = set()
    out: List[str] = []
    for token in tokens:
        if len(token) < 3 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def parse_analysis_json(content: str) -> dict:
    """Best-effort JSON object extraction from an LLM analysis response.

    Mirrors the tolerance of ``TaskRouter._parse_llm_json``: raw JSON, a fenced
    ```json block, or a bare ``{...}`` object embedded in prose.
    """
    text = (content or "").strip()
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            loaded = json.loads(match.group(1))
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            loaded = json.loads(match.group(0))
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass

    return {}


class LearningEngine:
    """Three-level self-learning for the orchestrator.

    All collaborators are injectable: ``long_memory`` (required — the store),
    ``llm_provider`` (Level 2 causal analysis; defaults to the shared provider)
    and ``redis_client`` (Level 3 routing confidence; defaults to the shared
    lazy client).
    """

    def __init__(
        self,
        long_memory,
        llm_provider: Optional[LLMProvider] = None,
        redis_client=None,
    ) -> None:
        self.long_memory = long_memory
        self.llm = llm_provider or default_provider
        self._redis = redis_client

    # ── collaborators (lazily resolved so import never connects) ─────────────
    @property
    def redis(self):
        """The active Redis client, or ``None`` if one cannot be built."""
        if self._redis is None:
            try:
                from app.security.redis_client import get_redis  # lazy

                self._redis = get_redis()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("LearningEngine: Redis unavailable (%s)", exc)
                return None
        return self._redis

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _agent_types(agent_results: Sequence[Any], routing_plan=None) -> List[str]:
        """Agent types that ran, falling back to the routing plan's list."""
        types: List[str] = []
        for result in agent_results or []:
            agent_type = getattr(result, "agent_type", None)
            if agent_type and agent_type not in types:
                types.append(agent_type)
        if not types and routing_plan is not None:
            types = list(getattr(routing_plan, "agents", []) or [])
        return types

    @staticmethod
    def _summarize(agent_results: Sequence[Any]) -> str:
        """A short human-readable summary of what the agents produced."""
        parts: List[str] = []
        for result in agent_results or []:
            text = getattr(result, "reasoning", None) or getattr(result, "content", "")
            snippet = str(text).strip().replace("\n", " ")[:200]
            if snippet:
                parts.append(f"{getattr(result, 'agent_type', 'agent')}: {snippet}")
        return " | ".join(parts) or "Task completed with no agent output"

    @staticmethod
    def _avg_confidence(agent_results: Sequence[Any]) -> float:
        scores = [float(getattr(r, "confidence_score", 1.0)) for r in agent_results or []]
        return sum(scores) / len(scores) if scores else 1.0

    def _confidence_breakdown(self, agent_results: Sequence[Any]) -> Dict[str, float]:
        return {
            getattr(r, "agent_type", "agent"): float(getattr(r, "confidence_score", 1.0))
            for r in agent_results or []
        }

    @staticmethod
    def _flatten(value: Any) -> Any:
        """Flatten containers to Chroma-legal scalar metadata values."""
        if isinstance(value, (str, int, float, bool)):
            return value
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return json.dumps(value, default=str)

    # ── Level 1 — storage ────────────────────────────────────────────────────
    async def store_success(
        self,
        task_id,
        goal: str,
        agent_results: Sequence[Any],
        routing_plan=None,
        cost: float = 0.0,
        quality: float = 0.0,
        tenant_id: str = "",
    ) -> None:
        """Store a successful task with the rich metadata that makes it useful.

        Adds structured fields (which agents ran, how they were grouped, the
        router's confidence, cost and quality) on top of the plain task result
        the orchestrator already stores, so retrieval can reason about *how* a
        past task was solved, not just *that* it was.
        """
        agent_types = self._agent_types(agent_results, routing_plan)
        parallel_groups = list(getattr(routing_plan, "parallel_groups", None) or [])
        extra_metadata = {
            "agent_types_used": ",".join(agent_types),
            "routing_confidence": float(getattr(routing_plan, "confidence", 0.5) or 0.5),
            "parallel_groups": self._flatten(
                ["+".join(str(a) for a in group) for group in parallel_groups]
            ),
            "agent_count": len(agent_types),
            "total_cost_usd": float(cost),
            "tenant_id": str(tenant_id or ""),
        }

        store_fn = getattr(self.long_memory, "store_task_result", None)
        if store_fn is None:
            return
        await store_fn(
            task_id,
            goal,
            self._summarize(agent_results),
            agent_types,
            cost,
            quality,
            extra_metadata=extra_metadata,
        )

    # ── Level 2 — causal analysis ────────────────────────────────────────────
    async def analyze_why(
        self,
        task_id,
        goal: str,
        agent_results: Sequence[Any],
        tenant_id: str = "",
    ) -> str:
        """Ask the LLM *why* this routing worked, store the causal pattern.

        Returns the ``why_it_worked`` string for logging. Any LLM failure logs a
        warning and returns an empty string — learning never crashes a task.
        """
        agent_types = self._agent_types(agent_results)
        quality = self._avg_confidence(agent_results)
        user_msg = _ANALYSIS_USER_TEMPLATE.format(
            goal=goal,
            agent_types=", ".join(agent_types) or "(none recorded)",
            quality=round(quality, 3),
            confidence_per_agent=json.dumps(self._confidence_breakdown(agent_results)),
        )

        try:
            completion = await self.llm.complete(
                [
                    LLMMessage("system", _ANALYSIS_SYSTEM_PROMPT),
                    LLMMessage("user", user_msg),
                ],
                temperature=0.0,
            )
            data = parse_analysis_json(completion.content)
        except Exception as exc:
            logger.warning("LearningEngine.analyze_why failed: %s", exc)
            return ""

        why_it_worked = str(data.get("why_it_worked", "") or "")
        goal_pattern = str(data.get("goal_pattern", "") or "")
        risk_factors = data.get("risk_factors", []) or []

        store_pattern = getattr(self.long_memory, "store_pattern", None)
        if store_pattern is not None:
            try:
                await store_pattern(
                    "causal",
                    f"Causal analysis for: {goal[:200]}",
                    {
                        "type": "causal",
                        "task_id": str(task_id),
                        "tenant_id": str(tenant_id or ""),
                        "goal_pattern": goal_pattern,
                        "why_it_worked": why_it_worked[:1000],
                        "risk_factors": self._flatten(risk_factors),
                    },
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("LearningEngine: pattern store failed: %s", exc)

        return why_it_worked

    # ── Level 3 — routing confidence ─────────────────────────────────────────
    async def update_routing_confidence(
        self,
        goal: str,
        agent_types: Iterable[str],
        quality: float,
        tenant_id: str,
    ) -> None:
        """Nudge Redis counters for every (keyword, agent) pair in this goal.

        A strong result (quality > :data:`STRONG_QUALITY`) increments by
        :data:`STRONG_SIGNAL`; a weak one (quality < :data:`WEAK_QUALITY`)
        decrements. Counters roll off after :data:`ROUTING_TTL_SECONDS`.
        """
        redis = self.redis
        if redis is None:
            return

        agents = [a for a in (agent_types or []) if a]
        if not agents:
            return

        delta = STRONG_SIGNAL if quality > STRONG_QUALITY else (1 if quality >= WEAK_QUALITY else -1)

        for keyword in extract_keywords(goal):
            for agent in agents:
                key = CONFIDENCE_KEY_TEMPLATE.format(
                    tenant=tenant_id, keyword=keyword, agent=agent
                )
                try:
                    if delta > 0:
                        await redis.incrby(key, delta)
                    else:
                        await redis.decr(key)
                    await redis.expire(key, ROUTING_TTL_SECONDS)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("LearningEngine: confidence update failed: %s", exc)
                    return

    async def get_routing_hints(
        self,
        goal: str,
        candidate_agents: Optional[Iterable[str]] = None,
        tenant_id: str = "",
        limit: int = 5,
    ) -> List[tuple[str, str, int]]:
        """Top ``(keyword, agent, score)`` confidence pairs for a goal.

        Read by ``TaskRouter.plan`` (Step 3.2) to bias routing toward what has
        worked before. Returns an empty list when Redis is unavailable — the
        router must degrade gracefully.
        """
        redis = self.redis
        if redis is None:
            return []

        candidates = list(candidate_agents or [])
        scored: List[tuple[str, str, int]] = []
        for keyword in extract_keywords(goal):
            agents = candidates or []
            if not agents:
                # No candidate list supplied: try the known agent registry.
                from app.agents.factory import AGENT_CLASSES  # lazy

                agents = list(AGENT_CLASSES.keys())
            for agent in agents:
                key = CONFIDENCE_KEY_TEMPLATE.format(
                    tenant=tenant_id, keyword=keyword, agent=agent
                )
                try:
                    raw = await redis.get(key)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("LearningEngine: hint read failed: %s", exc)
                    return []
                if raw is None:
                    continue
                try:
                    score = int(raw)
                except (TypeError, ValueError):
                    continue
                if score > 0:
                    scored.append((keyword, agent, score))

        scored.sort(key=lambda item: item[2], reverse=True)
        return scored[:limit]

    # ── failure learning ─────────────────────────────────────────────────────
    async def learn_from_failure(
        self,
        task_id,
        goal: str,
        error: str,
        failed_agent: str,
        tenant_id: str = "",
    ) -> str:
        """Store a failure with causal metadata and penalize the failed agent.

        The raw failure is already stored by the orchestrator; this adds the
        Level 2 "why did it fail" analysis and the Level 3 negative signal so
        the router stops choosing a failing agent for this kind of goal.
        """
        analysis = await self._analyze_failure(task_id, goal, error, failed_agent, tenant_id)

        store_failure = getattr(self.long_memory, "store_failure", None)
        if store_failure is not None:
            try:
                await store_failure(
                    task_id,
                    goal,
                    f"{failed_agent}: {error}"[:2000],
                    failed_agent,
                    extra_metadata={
                        "causal": analysis.get("why_it_failed", "")[:1000],
                        "goal_pattern": analysis.get("goal_pattern", "")[:500],
                        "risk_factors": self._flatten(analysis.get("risk_factors", [])),
                        "tenant_id": str(tenant_id or ""),
                    },
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("LearningEngine: failure store failed: %s", exc)

        await self.update_routing_confidence(goal, [failed_agent], 0.0, tenant_id)
        return str(analysis.get("why_it_failed", "") or "")

    async def _analyze_failure(
        self,
        task_id,
        goal: str,
        error: str,
        failed_agent: str,
        tenant_id: str,
    ) -> dict:
        """Level 2 causal analysis for a failure (returns {} on LLM failure)."""
        user_msg = _FAILURE_USER_TEMPLATE.format(
            goal=goal, failed_agent=failed_agent, error=error,
        )
        try:
            completion = await self.llm.complete(
                [
                    LLMMessage("system", _FAILURE_SYSTEM_PROMPT),
                    LLMMessage("user", user_msg),
                ],
                temperature=0.0,
            )
            return parse_analysis_json(completion.content)
        except Exception as exc:
            logger.warning("LearningEngine._analyze_failure failed: %s", exc)
            return {}
