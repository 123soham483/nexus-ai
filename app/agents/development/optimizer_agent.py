"""OptimizerAgent — improves code performance without breaking correctness.

A concrete agent (Phase 2) that follows the CoderAgent pattern: it inherits
the shared ``BaseAgent.execute`` lifecycle (memory → prompts → LLM → parse →
confidence → LTM store) and specializes the system prompt, the parsed output
sections (ANALYSIS / CODE / RESULTS), and the confidence scoring.
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class OptimizerAgent(BaseAgent):
    """Concrete agent that optimizes code for speed and efficiency."""

    AGENT_TYPE = "optimizer"
    agent_type = "optimizer"

    _SYSTEM_PROMPT = """You are an expert performance engineer specializing in optimizing code
for speed, memory, and efficiency without breaking correctness. You:
- Profile and identify actual bottlenecks before optimizing
- Preserve observable behavior while improving performance
- Choose appropriate algorithms and data structures
- Document expected gains so results are measurable

When given an optimization task, always respond in this EXACT structure:

ANALYSIS:
<what is slow or inefficient and why — with evidence>

CODE:
<the complete, optimized implementation — never truncate>

RESULTS:
<expected performance impact and how to measure it>

Never truncate the code. Always provide the complete implementation."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract ANALYSIS:, CODE:, RESULTS: sections from raw LLM output.
        Returns: {"analysis": str, "code": str, "results": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {"analysis": "", "code": "", "results": "", "raw": raw or ""}
        if not raw:
            return result

        analysis = re.search(
            r"ANALYSIS:\s*(.*?)(?=CODE:|RESULTS:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        code = re.search(
            r"CODE:\s*(.*?)(?=RESULTS:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        results = re.search(
            r"RESULTS:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if analysis:
            result["analysis"] = analysis.group(1).strip()
        if code:
            result["code"] = code.group(1).strip()
        if results:
            result["results"] = results.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("analysis"):
            score += 0.3
        if parsed.get("code") and len(parsed["code"]) > 50:
            score += 0.4
        if parsed.get("results"):
            score += 0.2
        code = parsed.get("code", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
