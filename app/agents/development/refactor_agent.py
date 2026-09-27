"""RefactorAgent — improves code structure without changing behavior.

A concrete agent (Phase 2) that follows the CoderAgent pattern: it inherits
the shared ``BaseAgent.execute`` lifecycle (memory → prompts → LLM → parse →
confidence → LTM store) and specializes the system prompt, the parsed output
sections (ASSESSMENT / CODE / EXPLANATION), and the confidence scoring.
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class RefactorAgent(BaseAgent):
    """Concrete agent that restructures code for clarity and maintainability."""

    AGENT_TYPE = "refactor"
    agent_type = "refactor"

    _SYSTEM_PROMPT = """You are an expert software refactoring engineer specializing in improving
code structure without changing behavior. You:
- Identify structural problems (duplication, coupling, complexity)
- Apply safe refactorings that preserve semantics
- Follow language idioms and design principles
- Explain what improved and why it matters

When given a refactoring task, always respond in this EXACT structure:

ASSESSMENT:
<what structural issues exist in the current code and why>

CODE:
<the complete, refactored implementation — never truncate>

EXPLANATION:
<what changed, the design decisions, and why it is better>

Never truncate the code. Always provide the complete implementation."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract ASSESSMENT:, CODE:, EXPLANATION: sections from raw LLM output.
        Returns: {"assessment": str, "code": str, "explanation": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {"assessment": "", "code": "", "explanation": "", "raw": raw or ""}
        if not raw:
            return result

        assessment = re.search(
            r"ASSESSMENT:\s*(.*?)(?=CODE:|EXPLANATION:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        code = re.search(
            r"CODE:\s*(.*?)(?=EXPLANATION:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        explanation = re.search(
            r"EXPLANATION:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if assessment:
            result["assessment"] = assessment.group(1).strip()
        if code:
            result["code"] = code.group(1).strip()
        if explanation:
            result["explanation"] = explanation.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("assessment"):
            score += 0.3
        if parsed.get("code") and len(parsed["code"]) > 50:
            score += 0.4
        if parsed.get("explanation"):
            score += 0.2
        code = parsed.get("code", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
