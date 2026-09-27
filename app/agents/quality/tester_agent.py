"""TesterAgent — writes test suites and (Phase 3) RUNS them in a sandbox.

A concrete agent that follows the CoderAgent pattern: it inherits the shared
``BaseAgent.execute`` lifecycle and specializes the system prompt, the parsed
output sections (TEST_PLAN / TEST_CODE / EXPECTED_RESULTS), and the confidence
scoring. Routed to the cheap gemini-flash model (spec) because test generation
is high-volume and low-risk.

Phase 3, Step 3.6: the agent no longer just *claims* the tests pass. Its
``post_process`` hook executes ``TEST_CODE`` inside the
:class:`~app.security.sandbox.DockerSandbox` (no network, read-only rootfs,
unprivileged user) and folds the real exit code and output into ``parsed``, so
the confidence score reflects an observed result rather than an assertion. When
no sandbox is available the hook degrades to ``executed: False`` — a missing
docker daemon must not fail a task.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from app.agents.base import BaseAgent
from app.config import settings
from app.observability.tracer import TOOL_SUCCESS

logger = logging.getLogger(__name__)


class TesterAgent(BaseAgent):
    """Concrete agent that writes and runs tests for produced code."""

    AGENT_TYPE = "tester"
    agent_type = "tester"

    #: the planning section is this agent's "reasoning" for the AgentRun row
    _reasoning_keys = ("test_plan",)
    #: prefer the actual test code as the long-term-memory summary
    _summary_keys = ("test_code", "expected_results", "test_plan")

    _SYSTEM_PROMPT = """You are an expert QA engineer specializing in writing thorough, reliable
test suites. You write tests that:
- Cover happy paths, edge cases, and failure modes
- Are deterministic and fast (no flaky sleeps or network calls)
- Follow the project's testing framework and idioms
- Verify behavior, not implementation details

When given a testing task, always respond in this EXACT structure:

TEST_PLAN:
<what to test, the edge cases, and the testing strategy>

TEST_CODE:
<the complete, runnable test suite — never truncate>

EXPECTED_RESULTS:
<what passing looks like and the exact commands to run the tests>

Never truncate the test code. Always provide the complete implementation."""

    system_prompt: str = _SYSTEM_PROMPT

    def __init__(
        self,
        llm=None,
        short_term=None,
        long_term=None,
        *,
        agent_id: Optional[str] = None,
        provider: Optional[str] = None,
        sandbox=None,
        tracer=None,
    ) -> None:
        super().__init__(
            llm=llm,
            short_term=short_term,
            long_term=long_term,
            agent_id=agent_id,
            provider=provider,
            tracer=tracer,
        )
        #: Injected sandbox (tests, or a pre-probed instance). ``None`` means
        #: "probe lazily on first use" — see ``_resolve_sandbox``.
        self.sandbox = sandbox
        self._sandbox_unavailable = False

    def parse_response(self, raw: str) -> dict:
        """
        Extract TEST_PLAN:, TEST_CODE:, EXPECTED_RESULTS: sections from raw LLM
        output.
        Returns: {"test_plan": str, "test_code": str, "expected_results": str,
                  "raw": str}
        Missing sections become empty strings; the full text stays in "raw".
        """
        result = {
            "test_plan": "",
            "test_code": "",
            "expected_results": "",
            "raw": raw or "",
        }
        if not raw:
            return result

        plan = re.search(
            r"TEST_PLAN:\s*(.*?)(?=TEST_CODE:|EXPECTED_RESULTS:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        code = re.search(
            r"TEST_CODE:\s*(.*?)(?=EXPECTED_RESULTS:|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        results = re.search(
            r"EXPECTED_RESULTS:\s*(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        if plan:
            result["test_plan"] = plan.group(1).strip()
        if code:
            result["test_code"] = code.group(1).strip()
        if results:
            result["expected_results"] = results.group(1).strip()
        return result

    # ── sandbox execution (Phase 3, Step 3.6) ────────────────────────────────
    async def _resolve_sandbox(self):
        """The injected sandbox, or a probed default — ``None`` when unusable.

        Probed at most once per agent instance: a missing docker daemon is a
        normal state (local dev, CI), not an error to log on every run.
        """
        if self.sandbox is not None:
            return self.sandbox
        if not settings.SANDBOX_ENABLED:
            return None
        from app.security.sandbox import DockerSandbox  # lazy (heavy module)

        try:
            candidate = DockerSandbox()
            if await candidate.available():
                self.sandbox = candidate
            else:
                self._sandbox_unavailable = True
                return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("TesterAgent: sandbox probe failed (%s)", exc)
            self._sandbox_unavailable = True
            return None
        return self.sandbox

    async def post_process(
        self, parsed: Any, context: Dict[str, Any], task_id
    ) -> Any:
        """Execute the generated TEST_CODE in the sandbox and record the result.

        Never raises and never blocks a task: no code, no sandbox, or a failing
        sandbox all leave ``parsed`` usable and simply set ``executed`` False
        with a reason.
        """
        if not isinstance(parsed, dict):
            return parsed

        parsed.setdefault("executed", False)
        code = parsed.get("test_code") or ""
        if not code.strip():
            parsed["execution_skipped"] = "no test code was generated"
            return parsed
        if not context.get("run_tests", True):
            parsed["execution_skipped"] = "run_tests disabled by context"
            return parsed

        try:
            sandbox = await self._resolve_sandbox()
            if sandbox is None:
                parsed["execution_skipped"] = "sandbox unavailable"
                return parsed
            # Running generated code is a tool call — give it its own span so a
            # trace shows exactly when and for how long the sandbox ran (Step 4.1).
            with self.tracer.tool_span(
                self.agent_type, "docker_sandbox"
            ) as span:
                result = await sandbox.run_python(code)
                span.set_attribute(TOOL_SUCCESS, bool(result.success))
                span.set_attribute("nexus.tool.exit_code", int(result.exit_code))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("TesterAgent: sandbox execution failed (%s)", exc)
            parsed["execution_skipped"] = f"sandbox error: {exc}"
            return parsed

        parsed["executed"] = True
        parsed["execution"] = result.to_dict()
        if not result.success:
            parsed["execution_failure"] = (
                result.stderr or result.error or f"exit code {result.exit_code}"
            )[:1000]
        return parsed

    def _calculate_confidence(self, parsed: dict) -> float:
        score = 0.0
        if parsed.get("test_plan"):
            score += 0.3
        if parsed.get("test_code") and len(parsed["test_code"]) > 50:
            score += 0.4
        if parsed.get("expected_results"):
            score += 0.2
        code = parsed.get("test_code", "")
        if any(kw in code for kw in ["def ", "class ", "function ", "const ", "async "]):
            score += 0.1

        # Evidence beats assertion: a green sandbox run is worth full marks, a
        # red one means the tests do not pass and the output is not trustworthy.
        if parsed.get("executed"):
            executed_ok = bool((parsed.get("execution") or {}).get("success"))
            score = min(1.0, score + 0.2) if executed_ok else min(score, 0.4)

        return min(score, 1.0)
