# NexusAI — Architecture

This document describes the **actual implementation** in `app/`. It is written
from the code, not from the original specification.

NexusAI is a multi-agent LLM orchestration platform. A single task goal is
routed to a team of specialized agents, executed with real per-agent cost and
token accounting, streamed live over WebSocket, and distilled into long-term
memory that improves the routing of later tasks.

---

## 1. System overview

```
                        ┌──────────────────────────────────────────────┐
                        │                FastAPI (app/main.py)          │
   HTTP / WS clients ──▶│  RequestId → RateLimit → CORS middleware      │
                        │  /api/v1/*  /metrics  /health  /ws/{task_id}  │
                        └───────────────┬──────────────────────────────┘
                                        │
                     ┌──────────────────┼───────────────────┐
                     ▼                  ▼                   ▼
              API routers          Auth (JWT)        WebSocket manager
              (auth, tasks,                              + broadcaster
               cost, memory,
               agents, observability)
                     │
                     ▼ (POST /tasks/ creates a row, then enqueues)
              ┌──────────────────┐
              │  Celery worker   │  app/workers/task_worker.py
              │  execute_task    │
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │   Orchestrator   │  app/core/orchestrator.py
              │  route → cost →  │
              │  agents → quality│
              │  → learn         │
              └───┬──────────┬───┘
                  │          │
      ┌───────────▼──┐   ┌───▼──────────────┐
      │  TaskRouter  │   │  Agent team       │
      │ app/core/    │   │  AgentFactory →   │
      │ router.py    │   │  BaseAgent        │
      └───┬──────────┘   └───┬───────────────┘
          │                  │
          │                  ├─── LLMProvider (LiteLLM) — fallback order
          │                  ├─── ShortTermMemory (Redis)
          │                  ├─── LongTermMemory (ChromaDB)
          │                  └─── DockerSandbox (untrusted code)
          │
      LearningEngine (app/memory/learning_engine.py)
        L1 store → L2 causal analysis → L3 routing confidence counters
          │
          ▼ Redis counters read back by TaskRouter on the next task
```

Data stores: **PostgreSQL** (tasks, users, agent runs, traces, cost records,
HITL rows), **Redis** (short-term memory, HITL pub/sub, rate-limit buckets,
routing-confidence counters), **ChromaDB** (long-term semantic memory).

---

## 2. Request flow (task lifecycle)

1. `POST /api/v1/tasks/` validates the goal + context (see §9), inserts a `Task`
   row scoped to the caller's tenant, and enqueues `execute_task` on Celery.
2. The worker resolves the task, builds an `Orchestrator`, and runs the pipeline.
3. The `Orchestrator` emits trace events at every stage; each event is persisted
   as a `Trace` row **and** pushed over WebSocket to `/ws/{task_id}` subscribers.
4. On success, the `LearningEngine` runs all three learning levels. On failure,
   `learn_from_failure` records the failure pattern so later routing can avoid it.

Pipeline events (`event_type`): `task_started`, `failure_patterns_checked`,
`routing_complete`, `cost_estimated`, `agent_spawned`, `agent_completed`,
`agent_error`, `quality_check`, `hallucination_check`, `learning_stored`,
`task_completed`, `task_failed`.

---

## 3. Orchestrator (`app/core/orchestrator.py`)

`Orchestrator.execute_task` is the whole pipeline:

- **Routing** — `TaskRouter.plan(goal, context, failures, tenant_id)` returns the
  agent team, a confidence score, and the rationale. The router consults learned
  routing-confidence counters (Level 3, §7) and can re-add an agent with a strong
  historical record that the LLM dropped.
- **Cost estimation** — per-agent estimated USD from `app/llm/routing.py`
  (`estimate_agent_cost`). Non-LLM agents estimate to `$0`.
- **Agent execution** — `_run_single_agent` calls `AgentFactory` → `BaseAgent`,
  records an `AgentRun`, and emits `agent_spawned` / `agent_completed`.
- **Hallucination** — the real `HallucinationDetector` score is extracted
  (`_hallucination_result`) and a bounded retry sweep re-runs failed agents.
- **Quality** — a Python post-query quality score; `passed` when `score >= 0.7`.
- **Learning** — `_learn_from_success_safe` (never breaks a successful task) and
  `learn_from_failure` on error.

Every emitted event is bracketed by an OpenTelemetry `task_span` (root); agent,
LLM, and tool work nest beneath it (§10).

---

## 4. Agents (`app/agents/`)

All 15 agents share the `BaseAgent.execute` lifecycle: load short-term memory →
build prompted messages → call the LLM provider → parse the response → validate
→ post-process (agent-specific) → return an `AgentResult`. See
[AGENTS.md](AGENTS.md) for each agent's purpose, model, inputs, and outputs.

- `AgentFactory` (`app/agents/factory.py`) is the single registry from which the
  orchestrator and API resolve agent types.
- `TesterAgent` additionally **executes** the tests it writes inside
  `DockerSandbox` and derives its confidence from the observed exit code.
- `HitlController` is the only non-LLM agent (`NON_LLM_AGENTS` in
  `app/llm/routing.py`): it creates a pending approval and awaits a human.

`BaseAgent` accepts an optional `tracer`, so tests inject a fake and production
injects the real `NexusTracer` — no agent imports OpenTelemetry directly.

---

## 5. Memory

Three tiers, all tenant-scoped:

| Tier | Impl | Backing store |
|------|------|---------------|
| Short-term | `app/memory/short_term.py` | Redis |
| Long-term | `app/memory/long_term.py` | ChromaDB (lazy-imported) |
| Learning | `app/memory/learning_engine.py` | ChromaDB + Redis + DB |

`LongTermMemory` exposes `extra_metadata` (an additive hook) so the learning
engine can attach causal metadata without changing existing call sites.
Collections: `nexusai_tasks`, `nexusai_failures`, `nexusai_patterns`.

Memory is exposed via `POST /memory/search`, `GET /memory/patterns`, and
`GET /memory/suggestions`.

---

## 6. LearningEngine (`app/memory/learning_engine.py`)

Three levels, each independently useful:

- **Level 1 — store.** Rich per-run metadata is written to long-term memory.
- **Level 2 — causal analysis.** An optional injected `llm_provider` explains
  *why* a run succeeded; failures are analysed by `analyze_why`.
- **Level 3 — routing confidence.** Keyword→agent confidence counters live in
  Redis and are read back by `TaskRouter` on subsequent tasks, so the plan
  shifts toward agents with a proven record for similar goals.

`scripts/learning_routing_demo.py` demonstrates the shift without changing any
production code path.

---

## 7. Routing (`app/core/router.py`, `app/llm/routing.py`)

- `app/llm/routing.py` holds the static tables: `PROVIDER_MODELS`,
  `AGENT_LLM_MAP`, `NON_LLM_AGENTS`, and `MODEL_PRICING`. It is the one place a
  concrete model string or price lives.
- `app/core/router.py` performs task-level planning: it inspects the goal and
  failure patterns, asks the LLM for a plan, then applies learned-confidence
  hints from Level 3 before returning the final team and confidence.

---

## 8. HITL (human-in-the-loop)

`app/hitl/` provides a store with two backends selected by
`HITL_STORE_BACKEND` (`memory` | `redis`, validated in `app/config.py`):

- `HitlStore` — in-process asyncio store (default for single-process dev).
- `RedisHitlStore` — cross-process store with pub/sub wake-ups so a Celery
  worker's approval request is visible to the API process that resolves it.

Celery time limits are settings-driven (`HITL_TASK_SOFT_TIME_LIMIT`,
`HITL_TASK_TIME_LIMIT`) and validated to stay above `HITL_TIMEOUT`, avoiding the
race where the soft limit killed a task exactly as its approval timed out.
Production compose sets `HITL_STORE_BACKEND=redis` for both `api` and `worker`.

---

## 9. Security

- **JWT auth** (`app/security/auth.py`) — access + refresh tokens via
  `python-jose`, bcrypt password hashing used directly.
- **Tenant isolation** — every task, cost, trace, memory, and observability query
  is filtered by the caller's `tenant_id`. `app/db/tenant_isolation.py` attaches
  tenant context to the session (`session.info`) and offers `verify_query`; it
  deliberately does **not** install a global SQLAlchemy listener, which would
  break migrations and system queries.
- **Input validation** (`app/schemas/task.py`) — goals are stripped and reject
  null bytes; context is limited to depth 3 and 20 keys per level, with
  suspicious keys/values rejected.
- **Prompt injection scanning** (`app/security/injection_scanner.py`) — 26 rules
  over 8 attack families with NFKC/zero-width normalisation and an injectable
  semantic layer. Two evidence classes: unambiguous rules block alone; weak
  signals only corroborate. Gated by `ENABLE_PROMPT_INJECTION_SCAN`.
- **Rate limiting** (`app/security/rate_limiter.py`) — Redis-backed, per-endpoint
  (`POST /tasks/` 10/min, `POST /auth/login` 5/min, `POST /memory/search`
  30/min). Responses carry `X-RateLimit-Remaining`; blocked requests return
  `429` with `Retry-After`.
- **Structured errors + request IDs** (`app/middleware/request_context.py`) —
  every request gets an `X-Request-ID` (generated UUID) echoed back, included in
  logs and error bodies. Errors return
  `{"error", "code", "request_id"}`; unhandled exceptions log server-side with a
  traceback and return a generic `INTERNAL_ERROR` with no stack trace.
- **Docker sandbox** (`app/security/sandbox.py`) — untrusted generated code runs
  in a throwaway container with `--network none`, a read-only rootfs,
  `--cap-drop ALL`, an unprivileged user, and bounded CPU/memory/PIDs. The
  program is fed over **stdin**, so nothing is ever mounted from the host.
  Gated by `SANDBOX_ENABLED`.

---

## 10. Observability

- **OpenTelemetry** (`app/observability/tracer.py`) — `NexusTracer` builds four
  span kinds: `task_span` (root), `agent_span` (child), `llm_span` (nested), and
  `tool_span` (nested). LLM spans record input/output tokens, cost, and latency.
  Lazy-imported; a no-op tracer is used when `ENABLE_OPENTELEMETRY` is off.
  Exporter endpoint from `OTEL_EXPORTER_ENDPOINT` (`http://jaeger:4317` in prod).
- **Prometheus** (`app/observability/metrics.py`) — a dedicated
  `CollectorRegistry` with counters/gauges/histograms for tasks, task duration,
  agent runs, LLM cost, LLM tokens, active tasks, pending HITL, and hallucination
  scores. Exposed at `GET /metrics`. (A separate tenant-scoped
  `GET /api/v1/observability/metrics` reports DB aggregates.)
- **Hallucination scoring** (`app/observability/hallucination_scorer.py`) —
  persists scores, keeps a tenant rolling average in Redis, and emits the
  histogram. Exposed at `GET /api/v1/observability/hallucination` with the tenant
  average, per-agent breakdown, and recent history.
- **Traces** — every pipeline event is a `Trace` row and a WebSocket message;
  `GET /api/v1/observability/traces` and `GET /api/v1/tasks/{id}/trace` replay
  them.

Prometheus scrapes `api:8000/metrics` (`monitoring/prometheus.yml`); Grafana
reads Prometheus in the production compose stack.

---

## 11. Deployment

- `docker-compose.yml` — development stack.
- `docker-compose.prod.yml` — production stack, **8 services**: `api`, `worker`,
  `nginx`, `postgres`, `redis`, `chromadb`, `prometheus`, `grafana`. (The
  original spec said "7"; the actual required service list is 8.)
- `Dockerfile` — one image serving both API and worker; the command is chosen
  per service in compose.
- `.github/workflows/ci.yml` — mypy, pytest with an 80% coverage gate, coverage
  upload, compose validation, Docker build, and a health check.

Heavy dependencies (`chromadb`, `litellm`, `sentence-transformers`, `torch`,
`docker`, `opentelemetry`) are **lazy-imported** and intentionally omitted from
`requirements-dev.txt`; unit tests inject fakes/mocks. `requirements.txt` is the
full set used by the Docker image.
