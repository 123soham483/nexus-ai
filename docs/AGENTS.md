# NexusAI — Agents

NexusAI ships 15 agents. Fourteen are LLM agents sharing the `BaseAgent.execute`
lifecycle (short-term memory → prompts → LLM → parse → validate → post-process);
one (`hitl_controller`) never calls an LLM.

**Model resolution.** Concrete model strings come from `PROVIDER_MODELS` and the
per-agent provider from `AGENT_LLM_MAP` in `app/llm/routing.py`. The table below
uses the provider short-name; the resolved LiteLLM model string is in
parentheses. Agents absent from `AGENT_LLM_MAP` use `DEFAULT_LLM_PROVIDER`.

**Inputs.** Every LLM agent receives the task goal plus assembled `context`
(a dict) and any short-term memory the orchestrator injects. **Outputs.** Every
LLM agent returns an `AgentResult` with `output` (the parsed dict), `success`,
`confidence`, `tokens_used`, and `cost_usd`.

| Agent | Purpose | Provider (model) |
|-------|---------|------------------|
| `coder` | Generate clean, production-ready code | gemini (`gemini/gemini-2.5-flash`) |
| `debugger` | Find root causes and write verified fixes | gemini |
| `optimizer` | Optimize code for speed and efficiency | gemini |
| `refactor` | Restructure code for clarity and maintainability | gemini |
| `tester` | Write tests **and run them in the sandbox** | gemini (`gemini/gemini-2.5-flash`) |
| `reviewer` | Produce structured, actionable code reviews | gemini |
| `security` | Perform structured security audits | gemini |
| `docs` | Document code for developers | gemini |
| `research` | Produce sourced research on a topic | gemini |
| `summarizer` | Summarize code, docs, or conversation history | gemini |
| `planner` | Turn a goal into an ordered plan | gemini |
| `validator` | Validate outputs against acceptance criteria | gemini |
| `hallucination_detector` | Check outputs for unsupported claims | gemini |
| `cost_controller` | Estimate and control agent-run costs | gemini |
| `hitl_controller` | Gate a pipeline step behind human approval | — (no LLM) |

---

## Development agents (`app/agents/development/`)

### `coder`
- **Purpose:** write clean, production-ready code.
- **Inputs:** goal, context, any prior code in short-term memory.
- **Outputs:** `{code, language, explanation, ...}` parsed from the response.
- **Spawned when:** the plan needs net-new code (the common case).

### `debugger`
- **Purpose:** find root causes and write verified fixes.
- **Inputs:** goal, the failing code and/or error, context.
- **Outputs:** `{root_cause, fix, explanation, ...}`.
- **Spawned when:** the goal mentions bugs, errors, or failures, or the router
  detects a debugging intent.

### `optimizer`
- **Purpose:** optimize code for speed and efficiency.
- **Inputs:** goal, the code to optimize, context.
- **Outputs:** `{optimized_code, changes, expected_impact, ...}`.
- **Spawned when:** the goal asks for performance improvements.

### `refactor`
- **Purpose:** restructure code for clarity and maintainability without changing
  behavior.
- **Inputs:** goal, the code to refactor, context.
- **Outputs:** `{refactored_code, changes, rationale, ...}`.
- **Spawned when:** the goal asks for cleanup/restructuring.

---

## Quality agents (`app/agents/quality/`)

### `tester`
- **Purpose:** write tests for produced code and **execute** them.
- **Inputs:** goal, the code under test, context.
- **Outputs:** test code plus, after running, an observed exit code used to
  derive confidence. Runs inside `DockerSandbox` when `SANDBOX_ENABLED`.
- **Spawned when:** code was produced and verification is warranted.

### `reviewer`
- **Purpose:** produce structured, actionable code reviews.
- **Inputs:** goal, the code/diff to review, context.
- **Outputs:** `{summary, issues, strengths, verdict, ...}`.
- **Spawned when:** the plan includes a review step for produced code.

### `security`
- **Purpose:** perform structured security audits.
- **Inputs:** goal, code/config to audit, context.
- **Outputs:** `{vulnerabilities, severity, remediation, ...}`.
- **Spawned when:** the goal or artifacts touch security-sensitive surfaces.

---

## Knowledge agents (`app/agents/knowledge/`)

### `docs`
- **Purpose:** document code for developers.
- **Inputs:** goal, the code to document, context.
- **Outputs:** `{documentation, sections, ...}`.
- **Spawned when:** the plan asks for documentation output.

### `research`
- **Purpose:** produce sourced research on a topic.
- **Inputs:** goal, context, short-term memory.
- **Outputs:** `{findings, sources, summary, ...}`.
- **Spawned when:** the goal requires investigation beyond the repo.

### `summarizer`
- **Purpose:** summarize code, docs, or conversation history.
- **Inputs:** goal, the material to summarize, context.
- **Outputs:** `{summary, key_points, ...}`.
- **Spawned when:** the plan includes a consolidation step.

---

## Coordination agents (`app/agents/coordination/`)

### `planner`
- **Purpose:** turn a goal into an ordered plan.
- **Inputs:** goal, context, failure patterns.
- **Outputs:** `{steps, order, rationale, ...}`.
- **Spawned when:** the router judges the goal complex enough to benefit from
  explicit planning.

### `validator`
- **Purpose:** validate outputs against acceptance criteria.
- **Inputs:** goal, the outputs to validate, context.
- **Outputs:** `{passed, criteria, failures, ...}`.
- **Spawned when:** the plan includes a validation gate.

### `hallucination_detector`
- **Purpose:** check outputs for unsupported claims.
- **Inputs:** goal, the outputs to check, context.
- **Outputs:** a real hallucination `score` (0–1) consumed by the orchestrator to
  drive a bounded retry sweep. Persisted and averaged (tenant rolling average in
  Redis) via `HallucinationScorer`.
- **Spawned when:** the plan includes a fact-checking step.

### `cost_controller`
- **Purpose:** estimate and control agent-run costs.
- **Inputs:** goal, the planned team and estimated tokens, context.
- **Outputs:** `{estimated_cost, budget_status, recommendation, ...}`.
- **Spawned when:** the plan includes a budget check.

### `hitl_controller` (non-LLM)
- **Purpose:** gate a pipeline step behind human approval.
- **Inputs:** goal, the proposed action, context.
- **Outputs:** creates a pending `HitlRequest`, then awaits a human decision
  (`approved` / `rejected`) via the HITL store. Cost is always `$0` because it is
  listed in `NON_LLM_AGENTS`.
- **Spawned when:** a plan step is marked as requiring human approval. In
  production `HITL_STORE_BACKEND=redis`, so the API process can resolve a request
  the Celery worker created.
