"""CoderAgent — writes production-ready code in any language.

A concrete agent (Step 1.9) that follows the CoderAgent pattern: it inherits
the shared ``BaseAgent.execute`` lifecycle (memory → prompts → LLM → parse →
confidence → LTM store) and specializes the system prompt, the parsed output
sections (REASONING / CODE / EXPLANATION), and the confidence scoring.
"""
from __future__ import annotations

from typing import Any, Dict

from app.agents.base import BaseAgent


class CoderAgent(BaseAgent):
    """Concrete agent that generates clean, production-ready code via Claude."""

    AGENT_TYPE = "coder"
    agent_type = "coder"
    #: low temperature for consistent, deterministic code output (spec 1.9)
    temperature = 0.1

    _SYSTEM_PROMPT = """You are an expert software engineer specializing in writing clean,
production-ready code. You write code that is:
- Correct and handles edge cases
- Well-commented and readable
- Following language best practices and idioms
- Secure (no hardcoded secrets, proper input validation, no SQL injection)
- Efficient (appropriate data structures and algorithms)

When given a coding task, always respond in this EXACT structure:

REASONING:
<explain your approach, what you plan to build and why>

CODE:
<the complete, runnable implementation — never truncate>

EXPLANATION:
<what the code does, important design decisions, usage examples>

Never truncate the code. Always provide the complete implementation."""

    # Override BaseAgent's writeable ``system_prompt`` attribute with the fixed
    # coder prompt. (A read-only property would violate the base-class contract
    # — mypy ``[override]`` — so this is a plain class attribute instead.)
    system_prompt: str = _SYSTEM_PROMPT

    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        return self._SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract REASONING:, CODE:, EXPLANATION: sections from raw LLM output.
        Returns: {"reasoning": str, "code": str, "explanation": str, "raw": str}
        If a section is missing: empty string for that key, everything in "raw".
        """
        result = {"reasoning": "", "code": "", "explanation": "", "raw": raw or ""}
        if not raw:
            return result

        # Split by section headers (case-insensitive)
        # Handle: "REASONING:", "CODE:", "EXPLANATION:"
        # Everything between REASONING: and CODE: is reasoning
        # Everything between CODE: and EXPLANATION: is code
        # Everything after EXPLANATION: is explanation
        # If headers not found: put all content in "raw" only

        import re
        reasoning_match = re.search(r'REASONING:\s*(.*?)(?=CODE:|EXPLANATION:|$)', raw, re.DOTALL | re.IGNORECASE)
        code_match = re.search(r'CODE:\s*(.*?)(?=EXPLANATION:|$)', raw, re.DOTALL | re.IGNORECASE)
        explanation_match = re.search(r'EXPLANATION:\s*(.*?)$', raw, re.DOTALL | re.IGNORECASE)

        if reasoning_match:
            result["reasoning"] = reasoning_match.group(1).strip()
        if code_match:
            result["code"] = code_match.group(1).strip()
        if explanation_match:
            result["explanation"] = explanation_match.group(1).strip()

        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("reasoning"):
            score += 0.3
        if parsed.get("code") and len(parsed["code"]) > 50:
            score += 0.4
        if parsed.get("explanation"):
            score += 0.2
        code = parsed.get("code", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)

