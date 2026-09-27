"""PlannerAgent — decomposes goals into ordered, executable plans (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (ANALYSIS / PLAN / SUCCESS_CRITERIA), and the confidence
scoring. Routed to claude-sonnet-4-6 (spec) for strong planning.
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class PlannerAgent(BaseAgent):
    """Concrete agent that turns a goal into an ordered plan."""

    AGENT_TYPE = "planner"
    agent_type = "planner"

    #: the analysis section is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("analysis",)
    #: prefer the plan as the long-term-memory summary
    _summary_keys = ("plan", "analysis", "success_criteria")

    _SYSTEM_PROMPT = """You are an expert project planner specializing in decomposing goals into
clear, executable plans. You:
- Restate the goal precisely and surface ambiguities
- Identify dependencies and ordering constraints
- Define concrete, verifiable success criteria
- Estimate effort so the plan is actionable

When given a planning task, always respond in this EXACT structure:

ANALYSIS:
<your understanding of the goal, dependencies, and risks>

PLAN:
<the ordered, step-by-step plan — never truncate>

SUCCESS_CRITERIA:
<how to know the task is done — verifiable and specific>

Never truncate the plan. Always provide the complete output."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract ANALYSIS:, PLAN:, SUCCESS_CRITERIA: sections from raw LLM output.
        Returns: {"analysis": str, "plan": str, "success_criteria": str,
                  "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {
            "analysis": "",
            "plan": "",
            "success_criteria": "",
            "raw": raw or "",
        }
        if not raw:
            return result

        analysis = re.search(
            r"ANALYSIS:\s*(.*?)(?=PLAN:|SUCCESS_CRITERIA:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        plan = re.search(
            r"PLAN:\s*(.*?)(?=SUCCESS_CRITERIA:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        criteria = re.search(
            r"SUCCESS_CRITERIA:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if analysis:
            result["analysis"] = analysis.group(1).strip()
        if plan:
            result["plan"] = plan.group(1).strip()
        if criteria:
            result["success_criteria"] = criteria.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("analysis"):
            score += 0.3
        if parsed.get("plan") and len(parsed["plan"]) > 50:
            score += 0.4
        if parsed.get("success_criteria"):
            score += 0.2
        code = parsed.get("plan", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
