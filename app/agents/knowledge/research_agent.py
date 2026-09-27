"""ResearchAgent — investigates topics and synthesizes sourced findings (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (SUMMARY / FINDINGS / SOURCES), and the confidence scoring.
Routed to the gemini-pro model (spec) for deeper reasoning.
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class ResearchAgent(BaseAgent):
    """Concrete agent that produces sourced research on a topic."""

    AGENT_TYPE = "research"
    agent_type = "research"

    #: the findings are this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("findings", "summary")
    #: prefer the concise summary as the long-term-memory summary
    _summary_keys = ("summary", "findings", "sources")

    _SYSTEM_PROMPT = """You are an expert research analyst specializing in thorough, well-sourced
investigations. You:
- Frame the question precisely before answering
- Gather evidence from multiple perspectives
- Distinguish fact from inference, and cite sources
- Synthesize a clear bottom-line answer

When given a research task, always respond in this EXACT structure:

SUMMARY:
<the concise bottom-line answer to the research question>

FINDINGS:
<detailed findings with evidence, trade-offs, and nuance — never truncate>

SOURCES:
<citations or references backing the findings>

Never truncate the findings. Always provide the complete research."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract SUMMARY:, FINDINGS:, SOURCES: sections from raw LLM output.
        Returns: {"summary": str, "findings": str, "sources": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {"summary": "", "findings": "", "sources": "", "raw": raw or ""}
        if not raw:
            return result

        summary = re.search(
            r"SUMMARY:\s*(.*?)(?=FINDINGS:|SOURCES:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        findings = re.search(
            r"FINDINGS:\s*(.*?)(?=SOURCES:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        sources = re.search(
            r"SOURCES:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if summary:
            result["summary"] = summary.group(1).strip()
        if findings:
            result["findings"] = findings.group(1).strip()
        if sources:
            result["sources"] = sources.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("summary"):
            score += 0.3
        if parsed.get("findings") and len(parsed["findings"]) > 50:
            score += 0.4
        if parsed.get("sources"):
            score += 0.2
        code = parsed.get("findings", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
