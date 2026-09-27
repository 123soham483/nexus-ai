# NexusAI — API Reference

All application endpoints are mounted under `/api/v1` (`app/api/v1/router.py`)
except the root health checks, the Prometheus scrape endpoint, and the WebSocket.

**Authentication.** Endpoints marked *auth* require a bearer token:
`Authorization: Bearer <access_token>`. Most are additionally tenant-scoped —
they only ever read/write the caller's tenant and return `404` for another
tenant's resources.

**Error shape.** All error responses are structured
(see `app/middleware/request_context.py`):

```json
{ "error": "Human-readable error", "code": "NOT_FOUND", "request_id": "<uuid>" }
```

Every response carries `X-Request-ID`. Rate-limited endpoints also carry
`X-RateLimit-Remaining`; blocked calls return `429` with `Retry-After`.

Interactive docs: `GET /docs` (Swagger) and `GET /redoc`.

---

## Auth — `/api/v1/auth`

### `POST /register` — public, `201`
Body (`UserRegister`): `{ "email": EmailStr, "password": str(8..128), "full_name": str? }`

Creates the user **and provisions a fresh single-user tenant** to own them.

```bash
curl -X POST localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@b.com","password":"password123","full_name":"A B"}'
```
```json
{ "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```

### `POST /login` — public
Form-encoded (`OAuth2PasswordRequestForm`): `username=<email>&password=<secret>`

Limited to **5/minute**. On failure returns `401` (structured as `UNAUTHORIZED`).

```bash
curl -X POST localhost:8000/api/v1/auth/login \
  -d 'username=a@b.com&password=password123'
```
→ `Token` (same shape as register).

### `POST /refresh` — public
Body: `{ "refresh_token": str }` → `{ "access_token": ..., "token_type": "bearer" }`.

### `POST /logout` — auth
Blacklists the presented access token in Redis until its expiry →
`{ "message": "logged out" }`.

### `GET /me` — auth
→ `UserOut`: `{ id, email, full_name, is_active, is_superuser, tenant_id, created_at }`.

---

## Tasks — `/api/v1/tasks`

### `POST /` — auth, `201`
Body (`TaskCreate`):
```json
{ "goal": "Write and test a Python function that reverses a string",
  "context": {} }
```
- `goal` is stripped; null bytes rejected; `10..2000` chars.
- `context` is limited to depth 3 and 20 keys per level; suspicious keys/values
  rejected.
- The goal is scanned for prompt injection; a block returns **`400`**.
- If the tenant's monthly budget is exhausted, returns **`429`**.
- Limited to **10/minute**.

Creates the task and dispatches it to Celery. Response is `TaskResponse`:
```json
{ "id": "uuid", "goal": "...", "status": "pending",
  "estimated_cost_usd": null, "actual_cost_usd": 0.0,
  "quality_score": null, "agents_spawned": [],
  "created_at": "...", "started_at": null, "completed_at": null,
  "duration_seconds": null }
```

### `GET /` — auth
Query: `status?` (`TaskStatus`), `limit` (1..100, default 20), `offset` (≥0).
→ `{ "tasks": [TaskResponse], "total": int, "limit": int, "offset": int }`.

### `GET /{task_id}` — auth
→ `TaskDetailResponse` (extends `TaskResponse` with `result`, `routing_decision`,
`hallucination_score`). Another tenant's task → **`404`** `NOT_FOUND`.

### `DELETE /{task_id}` — auth
Best-effort cancellation. `400` if the task is not pending/routing/running.
→ `{ "message": "Task cancelled", "task_id": "uuid" }`.

### `GET /{task_id}/trace` — auth
Query: `limit?`, `offset?`. → `[TraceResponse]` (`{ id, task_id, event_type,
event_data, agent_type?, timestamp, sequence_number }`), oldest first.

### `GET /{task_id}/cost` — auth
→ `[CostRecordResponse]` (`{ id, task_id, agent_run_id?, user_id, tenant_id,
llm_model, input_tokens, output_tokens, cost_usd, recorded_at }`).

### HITL
- `GET /{task_id}/hitl/pending` — auth → `[HitlRequestResponse]`
- `GET /{task_id}/hitl/history` — auth → `[HitlRequestResponse]`
- `POST /{task_id}/hitl/resolve` — auth, body `HitlResolveRequest`:
  `{ "request_id": "uuid", "approved": true, "note": "optional" }`
  → `HitlRequestResponse`

---

## Cost — `/api/v1/cost`

### `POST /estimate` — auth
Body (`CostEstimateRequest`): `{ "goal": str?, "agent_types": [str] }`
(empty `agent_types` → the default routing plan). → `CostEstimateResponse`:
`{ "agents": [{ agent_type, model, estimated_tokens, estimated_cost_usd }],
"total_estimated_usd": float }`.

### `GET /budget` — auth
→ `{ monthly_budget_usd, current_month_spend_usd, remaining_usd, exceeded }`.

### `GET /history` — auth
Query: `days?`. → `[{ date, cost_usd, task_count }]`.

---

## Memory — `/api/v1/memory`

### `POST /search` — auth
Body (`MemorySearchRequest`): `{ "query": str(1..500),
"collection": "tasks"|"failures"|"patterns" = "tasks", "n_results": 1..20 = 5 }`.
Limited to **30/minute**. → `{ query, collection,
results: [{ content, metadata, similarity_score }] }`.

### `GET /patterns` — auth
Query: `limit?`. → `{ patterns: [{ content, pattern_type, pattern_data,
timestamp }], total }` — learned causal patterns, newest first.

### `GET /suggestions` — auth
Query: `goal` (required). → `{ goal, keywords, suggested_agents:
[{ agent, score, matched_keywords }], similar_tasks, risk_patterns, notes? }`.

---

## Agents — `/api/v1/agents`

### `GET /` — auth
→ `[AgentTypeInfo]` — the 15 registered agent types and their metadata.

### `GET /stats` — auth
→ `AgentsStatsResponse` — per-agent run counts / success rates for the tenant.

---

## Observability — `/api/v1/observability`

### `GET /metrics` — auth
→ `MetricsResponse`: `{ total_tasks, tasks_by_status, total_agent_runs,
total_cost_usd, total_tokens, avg_quality_score?, avg_duration_seconds? }`.

### `GET /hallucination` — auth
Query: `days` (1..90, default 30). → `HallucinationObservabilityResponse`:
`{ tenant_average, by_agent: {agent: float}, recent: [ {…} ] }`.

### `GET /traces` — auth
Query: `task_id?`, `event_type?`, `limit` (1..500, default 100), `offset` (≥0).
→ `[TraceResponse]`, newest first.

---

## Root / infrastructure

### `GET /metrics` — public
Prometheus exposition format (`text/plain; version=0.0.4`). Path configurable via
`PROMETHEUS_METRICS_PATH`. Not to be confused with the tenant-scoped
`/api/v1/observability/metrics`.

### `GET /health`, `GET /health/db`, `GET /health/redis` — public
Liveness/readiness: `{ "status": "ok", ... }`. `db` executes `SELECT 1`; `redis`
pings.

### `WS /ws/{task_id}` — public
On connect, replays the task's historical traces, then streams live events as
JSON: `{ "event": str, "data": {...}, "timestamp": iso, "sequence": int }`.

---

## Status codes

| Code | Meaning here |
|------|--------------|
| 200 | OK |
| 201 | Created (task/registration) |
| 400 | Injection block, invalid cancel, validation of business rules |
| 401 | Missing/invalid/expired/blacklisted token (`UNAUTHORIZED`) |
| 403 | Inactive user / superuser required |
| 404 | Missing resource **or** another tenant's resource (`NOT_FOUND`) |
| 409 | Email already registered |
| 422 | Schema validation failure (`VALIDATION_ERROR`) |
| 429 | Rate limit or budget exceeded (`RATE_LIMITED`) with `Retry-After` |
| 500 | Unhandled error (`INTERNAL_ERROR`, no stack trace exposed) |
