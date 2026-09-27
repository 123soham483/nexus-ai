"""DebuggerAgent — diagnoses bugs and produces verified fixes.

A concrete agent (Phase 2) that follows the CoderAgent pattern: it inherits
the shared ``BaseAgent.execute`` lifecycle (memory → prompts → LLM → parse →
confidence → LTM store) and specializes the system prompt, the parsed output
sections (SYMPTOM / ROOT_CAUSE / FIX / VERIFICATION), and the confidence
scoring. It consults past failure patterns (not just past tasks) because that
is the most relevant long-term memory for debugging.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.agents.base import BaseAgent


class DebuggerAgent(BaseAgent):
    """Concrete agent that finds root causes and writes verified fixes."""

    AGENT_TYPE = "debugger"
    agent_type = "debugger"

    _SYSTEM_PROMPT = """You are an expert debugging engineer specializing in finding and fixing
bugs in production code. You diagnose problems by:
- Reproducing and understanding the reported symptom
- Tracing the root cause precisely (not treating symptoms)
- Writing minimal, correct fixes that handle edge cases
- Proposing verification steps so the fix is provably correct

When given a debugging task, always respond in this EXACT structure:

SYMPTOM:
<what the reported symptom is and how to reproduce it>

ROOT_CAUSE:
<the precise underlying cause, with evidence>

FIX:
<the complete corrected code — never truncate>

VERIFICATION:
<how to verify the fix: tests, commands, expected outcomes>

Never truncate the fix. Always provide the complete implementation."""

    system_prompt: str = _SYSTEM_PROMPT

    # Debugging is most informed by past failures — search those first.
    async def _retrieve_memory(self, goal: str) -> List[str]:
        """Relevant past failure patterns for this bug, as plain strings."""
        if self.long_term is None or not goal:
            return []
        hits = await self.long_term.search_similar_failures(
            goal, n_results=self.memory_top_k
        )
        docs: List[str] = []
        for h in hits:
            doc = getattr(h, "content", None) or getattr(h, "document", None) or str(h)
            docs.append(doc)
        return docs

    def parse_response(self, raw: str) -> dict:
        """
        Extract SYMPTOM:, ROOT_CAUSE:, FIX:, VERIFICATION: sections from raw
        LLM output.
        Returns: {"symptom": str, "root_cause": str, "fix": str,
                  "verification": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {
            "symptom": "",
            "root_cause": "",
            "fix": "",
            "verification": "",
            "raw": raw or "",
        }
        if not raw:
            return result

        symptom = re.search(
            r"SYMPTOM:\s*(.*?)(?=ROOT_CAUSE:|FIX:|VERIFICATION:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        cause = re.search(
            r"ROOT_CAUSE:\s*(.*?)(?=FIX:|VERIFICATION:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        fix = re.search(
            r"FIX:\s*(.*?)(?=VERIFICATION:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        verification = re.search(
            r"VERIFICATION:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if symptom:
            result["symptom"] = symptom.group(1).strip()
        if cause:
            result["root_cause"] = cause.group(1).strip()
        if fix:
            result["fix"] = fix.group(1).strip()
        if verification:
            result["verification"] = verification.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("symptom"):
            score += 0.1
        if parsed.get("root_cause"):
            score += 0.3
        if parsed.get("fix") and len(parsed["fix"]) > 50:
            score += 0.4
        if parsed.get("verification"):
            score += 0.2
        code = parsed.get("fix", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
