"""SecurityAgent — audits code for vulnerabilities and remediations (Phase 2).

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (THREAT_MODEL / VULNERABILITIES / REMEDIATION), and the
confidence scoring. Runs at temperature 0.0 for deterministic, reproducible
security findings (spec).
"""
from __future__ import annotations

import re
from typing import Any

from app.agents.base import BaseAgent


class SecurityAgent(BaseAgent):
    """Concrete agent that performs structured security audits."""

    AGENT_TYPE = "security"
    agent_type = "security"

    #: deterministic output — identical findings for identical input (spec)
    temperature = 0.0
    #: the threat model is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("threat_model",)
    #: prefer the remediation as the long-term-memory summary
    _summary_keys = ("remediation", "vulnerabilities", "threat_model")

    _SYSTEM_PROMPT = """You are an expert application security engineer specializing in secure
code review. You audit code for:
- Injection (SQL, command, XSS, LDAP)
- Authentication and authorization flaws
- Hardcoded secrets and unsafe deserialization
- OWASP Top 10 vulnerabilities and CWE mapping

When given a security task, always respond in this EXACT structure:

THREAT_MODEL:
<what is in scope, trust boundaries, and the threat surface>

VULNERABILITIES:
<specific findings — CWE, severity, location, and exploit scenario>

REMEDIATION:
<concrete fixes and mitigations for each finding>

Never truncate the remediation. Always provide the complete audit."""

    system_prompt: str = _SYSTEM_PROMPT

    def parse_response(self, raw: str) -> dict:
        """
        Extract THREAT_MODEL:, VULNERABILITIES:, REMEDIATION: sections from raw
        LLM output.
        Returns: {"threat_model": str, "vulnerabilities": str,
                  "remediation": str, "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {
            "threat_model": "",
            "vulnerabilities": "",
            "remediation": "",
            "raw": raw or "",
        }
        if not raw:
            return result

        model = re.search(
            r"THREAT_MODEL:\s*(.*?)(?=VULNERABILITIES:|REMEDIATION:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        vulns = re.search(
            r"VULNERABILITIES:\s*(.*?)(?=REMEDIATION:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        remediation = re.search(
            r"REMEDIATION:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if model:
            result["threat_model"] = model.group(1).strip()
        if vulns:
            result["vulnerabilities"] = vulns.group(1).strip()
        if remediation:
            result["remediation"] = remediation.group(1).strip()
        return result

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("threat_model"):
            score += 0.3
        if parsed.get("vulnerabilities") and len(parsed["vulnerabilities"]) > 50:
            score += 0.4
        if parsed.get("remediation"):
            score += 0.2
        code = parsed.get("vulnerabilities", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1
        return min(score, 1.0)

    async def _store_success_memory(
        self, goal: str, parsed: Any, completion, confidence: float, task_id,
    ) -> None:
        """High-confidence audits become FAILURES the team learns from.

        Only reached when ``execute`` scored confidence above the threshold, and
        an audit that found vulnerabilities is exactly the failure pattern the
        debugger and router should see (they both search the failures
        collection). Clean audits (no vulnerabilities) fall back to normal
        task-result storage.
        """
        if self.long_term is None:
            return
        if isinstance(parsed, dict) and parsed.get("vulnerabilities"):
            parts = [f"Vulnerabilities: {parsed['vulnerabilities']}"]
            if parsed.get("remediation"):
                parts.append(f"Remediation: {parsed['remediation']}")
            store_fn = getattr(self.long_term, "store_failure", None)
            if store_fn is not None:
                await store_fn(
                    task_id,
                    goal,
                    "\n\n".join(parts)[:2000],
                    self.agent_type,
                )
                return
        # No findings found (or the memory backend lacks store_failure) — treat
        # this as a normal high-confidence task result.
        await super()._store_success_memory(
            goal, parsed, completion, confidence, task_id
        )
