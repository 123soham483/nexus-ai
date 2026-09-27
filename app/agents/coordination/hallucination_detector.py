"""HallucinationDetector — flags unsupported claims in agent output (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (CLAIMS / EVIDENCE / VERDICT), and the confidence scoring.
Runs at temperature 0.0 for deterministic detection (spec).
"""
from __future__ import annotations

import re

from app.agents.base import BaseAgent


class HallucinationDetector(BaseAgent):
    """Concrete agent that checks outputs for unsupported claims."""

    AGENT_TYPE = "hallucination_detector"
    agent_type = "hallucination_detector"

    #: deterministic detection — identical input gives identical verdicts (spec)
    temperature = 0.0
    #: the evidence section is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("evidence", "claims")
    #: prefer the evidence as the long-term-memory summary
    _summary_keys = ("evidence", "verdict", "claims")

    _SYSTEM_PROMPT = """You are an expert fact-checker specializing in detecting hallucinations in
AI-generated output. You:
- Extract every factual claim that can be checked
- Compare each claim against the provided context/evidence
- Classify claims as SUPPORTED, PARTIAL, or UNSUPPORTED
- Issue a clear verdict on whether the output is trustworthy

When given a detection task, always respond in this EXACT structure:

CLAIMS:
<the factual claims extracted from the output>

EVIDENCE:
<per-claim support status against the context — never truncate>

VERDICT:
<HALLUCINATION, PARTIAL, or CLEAN, with rationale>

Never truncate the evidence. Always provide the complete output."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract CLAIMS:, EVIDENCE:, VERDICT: sections from raw LLM output.
        Returns: {"claims": str, "evidence": str, "verdict": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {"claims": "", "evidence": "", "verdict": "", "raw": raw or ""}
        if not raw:
            return result

        claims = re.search(
            r"CLAIMS:\s*(.*?)(?=EVIDENCE:|VERDICT:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        evidence = re.search(
            r"EVIDENCE:\s*(.*?)(?=VERDICT:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        verdict = re.search(
            r"VERDICT:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if claims:
            result["claims"] = claims.group(1).strip()
        if evidence:
            result["evidence"] = evidence.group(1).strip()
        if verdict:
            result["verdict"] = verdict.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("claims"):
            score += 0.3
        if parsed.get("evidence") and len(parsed["evidence"]) > 50:
            score += 0.4
        if parsed.get("verdict"):
            score += 0.2
        code = parsed.get("evidence", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)
