"""CostController — analyzes and controls LLM spend for a plan (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (COST_ANALYSIS / ESTIMATE / RECOMMENDATIONS), and the
confidence scoring. Routed to the cheap gpt-3.5-turbo model (spec).
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class CostController(BaseAgent):
    """Concrete agent that estimates and controls agent-run costs."""

    AGENT_TYPE = "cost_controller"
    agent_type = "cost_controller"

    #: the analysis section is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("cost_analysis",)
    #: prefer the estimate as the long-term-memory summary
    _summary_keys = ("estimate", "recommendations", "cost_analysis")

    _SYSTEM_PROMPT = """You are an expert cost controller specializing in managing LLM spend for
multi-agent runs. You:
- Break down where cost comes from (tokens per agent, model rates)
- Project the total cost with explicit assumptions
- Recommend concrete ways to reduce spend without losing quality
- Flag budget overruns before they happen

When given a cost task, always respond in this EXACT structure:

COST_ANALYSIS:
<where the spend comes from, with reasoning>

ESTIMATE:
<the projected cost with assumptions — never truncate>

RECOMMENDATIONS:
<concrete ways to control or reduce spend>

Never truncate the estimate. Always provide the complete output."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract COST_ANALYSIS:, ESTIMATE:, RECOMMENDATIONS: sections from raw
        LLM output.
        Returns: {"cost_analysis": str, "estimate": str, "recommendations": str,
                  "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {
            "cost_analysis": "",
            "estimate": "",
            "recommendations": "",
            "raw": raw or "",
        }
        if not raw:
            return result

        analysis = re.search(
            r"COST_ANALYSIS:\s*(.*?)(?=ESTIMATE:|RECOMMENDATIONS:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        estimate = re.search(
            r"ESTIMATE:\s*(.*?)(?=RECOMMENDATIONS:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        recommendations = re.search(
            r"RECOMMENDATIONS:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if analysis:
            result["cost_analysis"] = analysis.group(1).strip()
        if estimate:
            result["estimate"] = estimate.group(1).strip()
        if recommendations:
            result["recommendations"] = recommendations.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("cost_analysis"):
            score += 0.3
        if parsed.get("estimate") and len(parsed["estimate"]) > 50:
            score += 0.4
        if parsed.get("recommendations"):
            score += 0.2
        code = parsed.get("estimate", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
