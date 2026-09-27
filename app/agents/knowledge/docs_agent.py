"""DocsAgent — writes clear, accurate developer documentation (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (OVERVIEW / DOCUMENTATION / USAGE), and the confidence scoring.
Routed to the cheap gemini-flash model (spec).
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class DocsAgent(BaseAgent):
    """Concrete agent that documents code for developers."""

    AGENT_TYPE = "docs"
    agent_type = "docs"

    #: the overview section is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("overview",)
    #: prefer the actual documentation as the long-term-memory summary
    _summary_keys = ("documentation", "usage", "overview")

    _SYSTEM_PROMPT = """You are an expert technical writer specializing in clear, accurate
documentation for developers. You write docs that:
- Explain what the code does and why it exists
- Show real, copy-pasteable usage examples
- Document parameters, return values, and edge cases
- Follow the project's documentation conventions

When given a documentation task, always respond in this EXACT structure:

OVERVIEW:
<what the code does at a high level and its purpose>

DOCUMENTATION:
<the complete documentation — README, API reference, or guide — never truncate>

USAGE:
<concrete usage examples: install, import, call, expected output>

Never truncate the documentation. Always provide the complete output."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract OVERVIEW:, DOCUMENTATION:, USAGE: sections from raw LLM output.
        Returns: {"overview": str, "documentation": str, "usage": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {"overview": "", "documentation": "", "usage": "", "raw": raw or ""}
        if not raw:
            return result

        overview = re.search(
            r"OVERVIEW:\s*(.*?)(?=DOCUMENTATION:|USAGE:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        documentation = re.search(
            r"DOCUMENTATION:\s*(.*?)(?=USAGE:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        usage = re.search(
            r"USAGE:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if overview:
            result["overview"] = overview.group(1).strip()
        if documentation:
            result["documentation"] = documentation.group(1).strip()
        if usage:
            result["usage"] = usage.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("overview"):
            score += 0.3
        if parsed.get("documentation") and len(parsed["documentation"]) > 50:
            score += 0.4
        if parsed.get("usage"):
            score += 0.2
        code = parsed.get("documentation", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
