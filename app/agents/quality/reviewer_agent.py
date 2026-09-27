"""ReviewerAgent — reviews code for quality, correctness, and style (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (REVIEW / FINDINGS / VERDICT), and the confidence scoring.
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class ReviewerAgent(BaseAgent):
    """Concrete agent that produces structured, actionable code reviews."""

    AGENT_TYPE = "reviewer"
    agent_type = "reviewer"

    #: the review summary is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("review",)
    #: prefer the findings as the long-term-memory summary
    _summary_keys = ("findings", "verdict", "review")

    _SYSTEM_PROMPT = """You are an expert code reviewer specializing in thorough, fair, actionable
code reviews. You evaluate code for:
- Correctness and edge cases
- Readability, maintainability, and idiomatic style
- Performance and security concerns
- Test coverage quality

When given a review task, always respond in this EXACT structure:

REVIEW:
<summary of what was reviewed and your overall assessment>

FINDINGS:
<numbered, specific findings — severity, location, and suggested fix>

VERDICT:
<approve or request changes, with rationale>

Never truncate the findings. Always provide the complete review."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract REVIEW:, FINDINGS:, VERDICT: sections from raw LLM output.
        Returns: {"review": str, "findings": str, "verdict": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {"review": "", "findings": "", "verdict": "", "raw": raw or ""}
        if not raw:
            return result

        review = re.search(
            r"REVIEW:\s*(.*?)(?=FINDINGS:|VERDICT:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        findings = re.search(
            r"FINDINGS:\s*(.*?)(?=VERDICT:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        verdict = re.search(
            r"VERDICT:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if review:
            result["review"] = review.group(1).strip()
        if findings:
            result["findings"] = findings.group(1).strip()
        if verdict:
            result["verdict"] = verdict.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("review"):
            score += 0.3
        if parsed.get("findings") and len(parsed["findings"]) > 50:
            score += 0.4
        if parsed.get("verdict"):
            score += 0.2
        code = parsed.get("findings", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
