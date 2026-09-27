"""TesterAgent executes what it wrote (Phase 3, Step 3.6)."""
from __future__ import annotations

import uuid

import pytest

# ``TesterAgent`` starts with "Test", so pytest would try to collect it as a
# test class (same opt-out as tests/unit/agents/test_tester_agent.py).
from app.agents.quality.tester_agent import TesterAgent as TesterAgentCls

TesterAgentCls.__test__ = False  # not a pytest test class
from app.llm import LLMProvider
from app.security.sandbox import SandboxResult

TesterAgent = TesterAgentCls

GOOD_TEST_CODE = """
def test_adds():
    assert 1 + 1 == 2

EXPECTED_RESULTS:
pytest passes
"""

#: What a model typically emits: three labelled sections.
_RAW = f"""TEST_PLAN:
cover the happy path and one edge case

TEST_CODE:
{GOOD_TEST_CODE}
"""


def _llm(content: str = _RAW) -> LLMProvider:
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        return {"content": content, "input_tokens": 10, "output_tokens": 20}

    return LLMProvider(complete_fn=_fn)


class FakeSandbox:
    """Records what was executed and returns a scripted result."""

    def __init__(self, result: SandboxResult | None = None, raises: Exception | None = None):
        self.result = result or SandboxResult(exit_code=0, stdout="2 passed")
        self.raises = raises
        self.executed = []

    async def run_python(self, code, **kwargs):
        self.executed.append(code)
        if self.raises is not None:
            raise self.raises
        return self.result


def _tester(sandbox=None, raw: str = _RAW) -> TesterAgent:
    return TesterAgent(llm=_llm(raw), sandbox=sandbox)


# ── happy path ───────────────────────────────────────────────────────────────

async def test_generated_test_code_is_executed_in_the_sandbox():
    sandbox = FakeSandbox()
    result = await _tester(sandbox).execute("write tests for factorial", {}, uuid.uuid4())

    assert len(sandbox.executed) == 1
    assert "def test_adds" in sandbox.executed[0]
    assert result.parsed["executed"] is True
    assert result.parsed["execution"]["success"] is True
    assert result.parsed["execution"]["stdout"] == "2 passed"


async def test_a_green_run_raises_confidence_over_an_unverified_suite():
    green = await _tester(FakeSandbox()).execute("test it", {}, uuid.uuid4())
    # No injected sandbox and SANDBOX_ENABLED is off in the suite → not executed.
    unverified = await TesterAgent(llm=_llm()).execute("test it", {}, uuid.uuid4())

    assert unverified.parsed["executed"] is False
    assert "execution_skipped" in unverified.parsed
    assert green.confidence_score > unverified.confidence_score


async def test_a_red_run_is_recorded_and_caps_confidence():
    failing = FakeSandbox(
        SandboxResult(exit_code=1, stdout="", stderr="AssertionError: 1 != 2")
    )
    result = await _tester(failing).execute("test it", {}, uuid.uuid4())

    assert result.parsed["executed"] is True
    assert result.parsed["execution"]["success"] is False
    assert "AssertionError" in result.parsed["execution_failure"]
    # A red sandbox run must not be reported as a high-confidence test suite.
    assert result.confidence_score <= 0.4


# ── graceful degradation ─────────────────────────────────────────────────────

async def test_no_test_code_skips_execution():
    sandbox = FakeSandbox()
    agent = _tester(sandbox, raw="TEST_PLAN:\nonly a plan, no code\n")

    result = await agent.execute("test it", {}, uuid.uuid4())

    assert sandbox.executed == []
    assert result.parsed["execution_skipped"] == "no test code was generated"


async def test_run_tests_can_be_disabled_per_task():
    sandbox = FakeSandbox()
    agent = _tester(sandbox)

    result = await agent.execute("test it", {"run_tests": False}, uuid.uuid4())

    assert sandbox.executed == []
    assert result.parsed["execution_skipped"] == "run_tests disabled by context"
    assert result.parsed["executed"] is False


async def test_no_sandbox_available_is_reported_not_failed():
    agent = _tester(sandbox=None)  # SANDBOX_ENABLED is off in the test suite

    result = await agent.execute("test it", {}, uuid.uuid4())

    assert result.success is True
    assert result.parsed["executed"] is False
    assert result.parsed["execution_skipped"] == "sandbox unavailable"


async def test_exploding_sandbox_does_not_fail_the_task():
    agent = _tester(FakeSandbox(raises=RuntimeError("docker exploded")))

    result = await agent.execute("test it", {}, uuid.uuid4())

    assert result.success is True
    assert result.parsed["executed"] is False
    assert "docker exploded" in result.parsed["execution_skipped"]


async def test_sandbox_probe_failure_is_swallowed():
    """A missing daemon must not raise out of the agent lifecycle."""
    async def _boom(*args, **kwargs):
        raise OSError("no docker")

    agent = TesterAgent(llm=_llm())
    agent._resolve_sandbox = _boom  # type: ignore[assignment]

    result = await agent.execute("test it", {}, uuid.uuid4())

    assert result.success is True
    assert result.parsed["executed"] is False


async def test_injected_sandbox_bypasses_the_enable_flag():
    """Injection is how tests (and an operator) force execution."""
    sandbox = FakeSandbox()
    result = await _tester(sandbox).execute("test it", {}, uuid.uuid4())
    assert sandbox.executed and result.parsed["executed"] is True
