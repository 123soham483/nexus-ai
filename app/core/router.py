"""TaskRouter — decides which agents to spawn and in what order."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.llm import LLMMessage, LLMProvider, default_provider


@dataclass
class RoutingPlan:
    agents: List[str]
    sequential: List[str]
    parallel_groups: List[List[str]]
    reasoning: str
    confidence: float
    estimated_tokens: Dict[str, int] = field(default_factory=dict)


DEFAULT_PLAN = RoutingPlan(
    agents=["planner", "coder", "tester", "validator"],
    sequential=["planner", "coder", "tester", "validator"],
    parallel_groups=[],
    reasoning="Default fallback plan used due to routing failure",
    confidence=0.5,
    estimated_tokens={"planner": 1000, "coder": 3000, "tester": 1500, "validator": 500},
)


_ROUTING_PROMPT = """You are an expert AI agent orchestration router.
Analyze the following goal and return a JSON routing plan.

Goal: {goal}
Context: {context}
Past failure patterns to avoid: {failure_patterns}

Return ONLY valid JSON in this exact format:
{{
  "agents": ["planner", "coder", "security", "tester", "docs", "validator"],
  "sequential": ["planner", "coder", "validator"],
  "parallel_groups": [["security", "tester", "docs"]],
  "reasoning": "explanation of why these agents were chosen",
  "confidence": 0.94,
  "estimated_tokens": {{"planner": 1000, "coder": 3000, "security": 1500}}
}}

Rules:
- validator is ALWAYS last
- planner is ALWAYS first if task has multiple steps
- security ALWAYS included if task involves auth/passwords/tokens
- tester ALWAYS included if task produces code
- parallel_groups contains agents that can run simultaneously
- sequential contains agents that must run in order
"""


#: Minimum learned confidence score before the router re-adds an agent the LLM
#: dropped (Phase 3, Step 3.2). Two strong wins (or one very strong run) is the
#: bar — one success is too noisy to overrule the LLM.
_LEARNED_AGENT_MIN_SCORE = 2


class TaskRouter:
    """LLM-powered router that returns a structured :class:`RoutingPlan`.

    When a :class:`~app.memory.learning_engine.LearningEngine` is injected the
    router becomes *self-correcting*: before planning it reads the learned
    (keyword → agent) confidence scores for this goal and feeds them to the LLM,
    then re-adds any agent the LLM dropped that has a strong track record. Both
    paths are best-effort — a missing/unreachable engine leaves Phase 2 routing
    untouched.
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        learning_engine=None,
    ) -> None:
        self.llm = llm_provider or default_provider
        #: Phase 3 self-learning hook (optional). See class docstring.
        self.learning_engine = learning_engine

    def _parse_llm_json(self, content: str) -> dict:
        """
        Extract JSON from LLM response.
        Handles: raw JSON, ```json blocks, JSON embedded in text.
        Returns parsed dict or raises ValueError.
        """
        import re
        # Try direct parse first
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            pass

        # Try extracting from code block
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding first { ... } block
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not extract JSON from LLM response: {content[:200]}")

    async def _learned_hints(self, goal: str, tenant_id: str) -> List[tuple[str, str, int]]:
        """Learned ``(keyword, agent, score)`` hints, or ``[]`` on any failure."""
        if self.learning_engine is None:
            return []
        try:
            return await self.learning_engine.get_routing_hints(
                goal, tenant_id=tenant_id
            )
        except Exception:  # learning must never break routing
            return []

    @staticmethod
    def _apply_learned_hints(
        plan: RoutingPlan, hints: List[tuple[str, str, int]]
    ) -> RoutingPlan:
        """Re-add agents with a strong learned track record that the LLM dropped.

        Learned agents are inserted just before ``validator`` (which must stay
        last). Agents already present are untouched, and the plan is returned
        unchanged when nothing needs adding — so a plan the LLM got right is
        byte-for-byte identical to Phase 2.
        """
        strong = [
            agent
            for _keyword, agent, score in hints
            if score >= _LEARNED_AGENT_MIN_SCORE and agent not in plan.agents
        ]
        if not strong:
            return plan

        # De-duplicate while preserving hint order.
        additions: List[str] = []
        for agent in strong:
            if agent not in additions:
                additions.append(agent)

        agents = [a for a in plan.agents if a != "validator"] + additions
        sequential = [a for a in plan.sequential if a != "validator"] + additions
        if "validator" in plan.agents:
            agents.append("validator")
            sequential.append("validator")

        learned = ", ".join(additions)
        reasoning = (
            f"{plan.reasoning}\nLearned routing: re-added {learned} "
            "(strong past results for this goal type)."
        ).strip()
        return RoutingPlan(
            agents=agents,
            sequential=sequential,
            parallel_groups=[list(g) for g in plan.parallel_groups],
            reasoning=reasoning,
            confidence=plan.confidence,
            estimated_tokens=dict(plan.estimated_tokens),
        )

    async def plan(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        failure_patterns: Optional[List[dict]] = None,
        tenant_id: str = "",
    ) -> RoutingPlan:
        context = context or {}
        failure_patterns = failure_patterns or []
        hints = await self._learned_hints(goal, tenant_id)
        hints_text = (
            ", ".join(f"{kw}->{agent}({score})" for kw, agent, score in hints)
            or "(none learned yet)"
        )
        
        system_msg = (
            "You are an expert AI agent orchestration router for NexusAI.\n"
            "Analyze the user's goal and return a routing plan as JSON only.\n"
            "No preamble, no explanation outside the JSON block."
        )
        
        user_msg = f"""Goal: {goal}
Context: {json.dumps(context, default=str)}
Past failure patterns to avoid: {json.dumps(failure_patterns, default=str)}
Learned routing hints (keyword->agent(score) from previous successes): {hints_text}

Return ONLY valid JSON in this exact format:
{{
  "agents": ["planner", "coder", "security", "tester", "docs", "validator"],
  "sequential": ["planner", "coder", "validator"],
  "parallel_groups": [["security", "tester", "docs"]],
  "reasoning": "explanation of why these agents were chosen",
  "confidence": 0.94,
  "estimated_tokens": {{"planner": 1000, "coder": 3000, "security": 1500, "tester": 2000, "docs": 800, "validator": 500}}
}}

Routing rules to follow:
- "auth", "login", "password", "jwt", "oauth", "token" in goal → ALWAYS include security
- "code", "build", "implement", "create", "write", "develop" → include coder
- Any task that produces code → include tester
- Task with 3+ implied steps → include planner FIRST
- ALWAYS include validator LAST
- ALWAYS include hallucination_detector after all content agents, before validator
- "document", "readme", "docs", "api docs" → include docs
- security + tester + docs CAN run in parallel after coder finishes
- planner MUST run before coder
- If failure_patterns provided → mention relevant avoidance in reasoning
- If learned routing hints are provided, prefer those agents for the goal text
"""

        try:
            result = await self.llm.complete(
                [
                    LLMMessage("system", system_msg),
                    LLMMessage("user", user_msg),
                ],
                temperature=0.0,
            )
            data = self._parse_llm_json(result.content)
            plan = RoutingPlan(
                agents=list(data.get("agents", DEFAULT_PLAN.agents)),
                sequential=list(data.get("sequential", DEFAULT_PLAN.sequential)),
                parallel_groups=[list(g) for g in data.get("parallel_groups", [])],
                reasoning=str(data.get("reasoning", "")),
                confidence=float(data.get("confidence", 0.5)),
                estimated_tokens=dict(data.get("estimated_tokens", {})),
            )
            return self._apply_learned_hints(plan, hints) if hints else plan
        except Exception:
            return DEFAULT_PLAN
