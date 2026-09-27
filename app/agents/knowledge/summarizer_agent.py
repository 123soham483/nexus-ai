"""SummarizerAgent — distills long content into faithful summaries (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (SUMMARY / KEY_POINTS / CONCLUSION), and the confidence
scoring. Routed to the cheap gemini-flash model (spec).
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class SummarizerAgent(BaseAgent):
    """Concrete agent that summarizes code, docs, or conversation history."""

    AGENT_TYPE = "summarizer"
    agent_type = "summarizer"

    #: the summary is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("key_points", "summary")
    #: prefer the concise summary as the long-term-memory summary
    _summary_keys = ("summary", "key_points", "conclusion")

    _SYSTEM_PROMPT = """You are an expert summarizer specializing in distilling long or complex
content into clear, faithful summaries. You:
- Preserve the author's intent and key claims
- Keep critical details, numbers, and caveats
- Remove redundancy without losing meaning
- State the conclusion and the most important points

When given a summarization task, always respond in this EXACT structure:

SUMMARY:
<the concise overall summary>

KEY_POINTS:
<the most important points, each as its own bullet — never truncate>

CONCLUSION:
<the bottom-line takeaway>

Never truncate the key points. Always provide the complete summary."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract SUMMARY:, KEY_POINTS:, CONCLUSION: sections from raw LLM output.
        Returns: {"summary": str, "key_points": str, "conclusion": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {
            "summary": "",
            "key_points": "",
            "conclusion": "",
            "raw": raw or "",
        }
        if not raw:
            return result

        summary = re.search(
            r"SUMMARY:\s*(.*?)(?=KEY_POINTS:|CONCLUSION:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        key_points = re.search(
            r"KEY_POINTS:\s*(.*?)(?=CONCLUSION:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        conclusion = re.search(
            r"CONCLUSION:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if summary:
            result["summary"] = summary.group(1).strip()
        if key_points:
            result["key_points"] = key_points.group(1).strip()
        if conclusion:
            result["conclusion"] = conclusion.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("summary"):
            score += 0.3
        if parsed.get("key_points") and len(parsed["key_points"]) > 50:
            score += 0.4
        if parsed.get("conclusion"):
            score += 0.2
        code = parsed.get("key_points", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
