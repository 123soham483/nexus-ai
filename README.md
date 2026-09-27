# NexusAI

A multi-agent LLM orchestration platform with real-time observability and
adaptive memory. A single task goal is routed to a team of specialized agents,
executed with real per-agent cost/token accounting, streamed live over
WebSocket, and distilled into long-term memory that improves routing for later
tasks.

---

## Features

- **15 agents** — coding, debugging, testing, review, security, docs, research,
  planning, validation, hallucination detection, cost control, and a non-LLM
  human-in-the-loop gate. See [docs/AGENTS.md](docs/AGENTS.md).
- **Adaptive memory** — short-term (Redis), long-term semantic (ChromaDB), and a
  three-level `LearningEngine` that feeds learned routing confidence back into
  the planner.
- **Real observability** — OpenTelemetry spans, Prometheus metrics at `/metrics`,
  persisted per-tenant hallucination scores, and full task trace replay.
- **Production hardening** — multi-tenant isolation, Redis-backed rate limiting,
  structured errors with request IDs, prompt-injection scanning, and a Docker
  sandbox for executing untrusted generated code.
- **Human-in-the-loop** — approval gates with a cross-process Redis store, so a
  Celery-worker approval is resolvable from the API process.

---

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up -d
curl http://localhost:8000/health
```

API docs: <http://localhost:8000/docs>

### Production

```bash
cp .env.prod.example .env.prod   # then edit secrets
docker compose -f docker-compose.prod.yml config   # validate
docker compose -f docker-compose.prod.yml up -d
```

The production stack has **8 services** — `api`, `worker`, `nginx`, `postgres`,
`redis`, `chromadb`, `prometheus`, `grafana`. (An earlier spec said "7"; the
actual required list is 8.)

---

## Development setup

```bash
python -m venv venv
# Linux/macOS: source venv/bin/activate   Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` is a curated subset for fast local testing on Python 3.13.
Heavy dependencies (`chromadb`, `litellm`, `sentence-transformers`, `torch`,
`docker`, `opentelemetry`) are **lazy-imported** and intentionally omitted —
unit tests inject fakes/mocks. `requirements.txt` is the full set used by the
Docker image.

---

## Tests

```bash
pytest tests/ -q                                       # full suite
pytest tests/ --cov=app --cov-report=term-missing      # coverage
python -m mypy app/                                    # static types
```

The suite must stay green and `mypy app/` clean. CI enforces an 80% coverage
gate.

Optional:

```bash
# Load test (requires a running API)
locust -f tests/load/locustfile.py --host=http://localhost:8000 --users 100 --spawn-rate 10

# Learning demonstration (repeated goals shift routing confidence)
PYTHONPATH=. python scripts/learning_routing_demo.py
```

---

## Architecture

Request flow: `POST /tasks/` → tenant-scoped DB row → Celery `execute_task` →
`Orchestrator` (route → estimate cost → run agents → quality → learn) → trace
events persisted and pushed over WebSocket.

Full detail — request flow, orchestrator, agents, memory, learning engine,
routing, HITL, security, and observability — is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Agent-by-agent reference is in
[docs/AGENTS.md](docs/AGENTS.md). The complete endpoint reference is in
[docs/API.md](docs/API.md).

---

## API

Base path `/api/v1` for application endpoints; health, Prometheus `/metrics`, and
`/ws/{task_id}` live at the root. Full reference: [docs/API.md](docs/API.md).

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/auth/register` | – | Register + provision tenant |
| POST | `/api/v1/auth/login` | – | OAuth2 password login (5/min) |
| POST | `/api/v1/auth/refresh` | – | New access token |
| POST | `/api/v1/auth/logout` | ✓ | Blacklist token |
| GET | `/api/v1/auth/me` | ✓ | Current user |
| POST | `/api/v1/tasks/` | ✓ | Create + dispatch task (10/min) |
| GET | `/api/v1/tasks/` | ✓ | List tasks |
| GET | `/api/v1/tasks/{id}` | ✓ | Task detail |
| DELETE | `/api/v1/tasks/{id}` | ✓ | Cancel task |
| GET | `/api/v1/tasks/{id}/trace` | ✓ | Task trace |
| GET | `/api/v1/tasks/{id}/cost` | ✓ | Task cost records |
| GET/POST | `/api/v1/tasks/{id}/hitl/...` | ✓ | Pending / history / resolve |
| POST | `/api/v1/cost/estimate` | ✓ | Cost estimate |
| GET | `/api/v1/cost/budget` | ✓ | Budget status |
| GET | `/api/v1/cost/history` | ✓ | Spend history |
| POST | `/api/v1/memory/search` | ✓ | Semantic memory search (30/min) |
| GET | `/api/v1/memory/patterns` | ✓ | Learned patterns |
| GET | `/api/v1/memory/suggestions` | ✓ | Routing suggestions |
| GET | `/api/v1/agents/` | ✓ | Agent types |
| GET | `/api/v1/agents/stats` | ✓ | Agent stats |
| GET | `/api/v1/observability/metrics` | ✓ | Tenant metrics |
| GET | `/api/v1/observability/hallucination` | ✓ | Hallucination scores |
| GET | `/api/v1/observability/traces` | ✓ | Tenant traces |
| GET | `/metrics` | – | Prometheus metrics |
| GET | `/health`, `/health/db`, `/health/redis` | – | Health checks |
| WS | `/ws/{task_id}` | – | Live task events + replay |

---

## Observability

- **Prometheus**: `GET /metrics`; scraped per `monitoring/prometheus.yml`
  (`api:8000`). Grafana reads Prometheus in the production stack.
- **OpenTelemetry**: set `ENABLE_OPENTELEMETRY=true` and
  `OTEL_EXPORTER_ENDPOINT` (default `http://jaeger:4317` in prod). Spans:
  task → agent → llm → tool.
- **Tenant metrics API**: `GET /api/v1/observability/metrics`.
- **Hallucination scores**: `GET /api/v1/observability/hallucination`.

---

## Deployment

- **CI** (`.github/workflows/ci.yml`): mypy → pytest with an 80% coverage gate →
  coverage upload → compose validation → Docker build → health check.
- **Image** (`Dockerfile`): one image serving both the API and the worker; the
  command is chosen per service in compose.
- **Prod config**: `docker-compose.prod.yml` + `.env.prod.example` (never commit
  `.env.prod`). Persistence is provided for Postgres, Redis, ChromaDB,
  Prometheus, and Grafana.

> Note: the Docker sandbox image (`SANDBOX_IMAGE`, default `python:3.11-slim`)
> should be pre-pulled on hosts that run untrusted code, so the first sandboxed
> run is not delayed by an image pull.

---

## Contributing

1. Create a branch.
2. Write code **and** tests; run `pytest tests/ -q` and `python -m mypy app/`.
3. Keep the suite green, coverage ≥ 80%, and `mypy` clean.
4. Open a PR — CI runs on push to `main` / `develop`.

Keep heavy dependencies lazy-imported and external clients injectable, so the
unit tests continue to run without them.
