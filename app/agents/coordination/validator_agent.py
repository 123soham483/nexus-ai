"""ValidatorAgent — checks outputs against requirements and issues a verdict (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (REQUIREMENTS / VALIDATION / VERDICT), and the confidence
scoring. Runs at temperature 0.0 for deterministic verdicts (spec) on the
cheap gpt-3.5-turbo model.
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class ValidatorAgent(BaseAgent):
    """Concrete agent that validates outputs against acceptance criteria."""

    AGENT_TYPE = "validator"
    agent_type = "validator"

    #: deterministic verdicts — identical input gives identical checks (spec)
    temperature = 0.0
    #: the validation detail is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("validation", "requirements")
    #: prefer the validation detail as the long-term-memory summary
    _summary_keys = ("validation", "verdict", "requirements")

    _SYSTEM_PROMPT = """You are an expert validator specializing in checking outputs against
acceptance criteria. You:
- Restate the requirements precisely before checking
- Check each requirement against concrete evidence
- Report PASS/FAIL per requirement with a reason
- Issue a clear final verdict

When given a validation task, always respond in this EXACT structure:

REQUIREMENTS:
<the acceptance criteria being checked>

VALIDATION:
<per-requirement results with evidence — never truncate>

VERDICT:
<PASS or FAIL, with rationale>

Never truncate the validation. Always provide the complete output."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract REQUIREMENTS:, VALIDATION:, VERDICT: sections from raw LLM output.
        Returns: {"requirements": str, "validation": str, "verdict": str,
                  "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {
            "requirements": "",
            "validation": "",
            "verdict": "",
            "raw": raw or "",
        }
        if not raw:
            return result

        requirements = re.search(
            r"REQUIREMENTS:\s*(.*?)(?=VALIDATION:|VERDICT:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        validation = re.search(
            r"VALIDATION:\s*(.*?)(?=VERDICT:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        verdict = re.search(
            r"VERDICT:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if requirements:
            result["requirements"] = requirements.group(1).strip()
        if validation:
            result["validation"] = validation.group(1).strip()
        if verdict:
            result["verdict"] = verdict.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("requirements"):
            score += 0.3
        if parsed.get("validation") and len(parsed["validation"]) > 50:
            score += 0.4
        if parsed.get("verdict"):
            score += 0.2
        code = parsed.get("validation", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
