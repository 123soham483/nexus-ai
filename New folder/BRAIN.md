# NexusAI Frontend — BRAIN.md
> Living memory of the frontend codebase.
> Last updated: 2026-09-27
> Current phase: Connected to the real NexusAI backend (VITE_USE_MOCK=false)
> Last completed: Live backend integration + REAL task execution verified end-to-end
> Next: WebSocket live push from the worker process (needs Redis pub/sub), real LLM keys

## Update — 2026-09-27 (part 6) — CRITICAL: proxy pointed at the STUB server

- The real cause of "tasks stuck PENDING forever": `VITE_PROXY_TARGET` was
  `http://127.0.0.1:8000` — the **loadtest stub server** (`scripts/loadtest_server.py`),
  whose Celery dispatch is a no-op. UI-created tasks were never dispatched at all.
- Fixed: `New folder/.env` now points `VITE_PROXY_TARGET=http://127.0.0.1:8001` (real
  backend). Verified live: a task created through the real UI went
  PENDING → ROUTING → RUNNING → FAILED (98s, Gemini daily-quota 429) with full traces.
- Use `bash scripts/start_dev.sh` to bring the stack up — it now hard-verifies broker
  connectivity, backend HTTP, celery inspect ping and `nexusai.execute_task` registration.
- No frontend code changes needed — only the proxy target env var.

---

## Update — 2026-09-27 (part 5) — "stuck PENDING" root-caused; live status transitions now visible

- Root cause was backend-side (not the UI): task status transitions were written with
  flush() but only committed at task end, so the list/detail pages showed PENDING for the
  whole LLM phase — which, with the Gemini daily-quota retry storm, meant 5-15 minutes.
- Backend now commits ROUTING/RUNNING immediately: the tasks list showed a task as
  **Running** live during execution, then Failed — verified in the real UI.
- Daily-quota 429s now fail fast (~100s total instead of 5-15 min).
- No frontend changes needed. Start the stack with `bash scripts/start_dev.sh`.

---

## Update — 2026-09-27 (part 4) — Gemini is now the MAIN provider; pending-bug root-caused

- Backend `.env` now makes Gemini the default provider for every agent
  (`DEFAULT_LLM_PROVIDER=gemini`), with the real key in `GOOGLE_API_KEY`.
- The "tasks stuck on PENDING" bug was the backend env pointing at Postgres/Redis ports that
  don't exist on this machine — fixed in `.env` (SQLite + fakeredis on :6389). With the stack
  running, tasks transition PENDING → RUNNING → COMPLETED/FAILED and never hang.
- LLM 429 rate-limit responses are now retried honoring Gemini's retry-delay hint.
- IMPORTANT for testing: the Gemini key is on the FREE tier — 20 requests/DAY for
  gemini-2.5-flash, and one task uses ~6 calls, so only ~3 tasks/day are possible before
  429s. Tasks then fail (correctly, with the quota error) until the daily reset.
- Full project overview + exact run commands are documented in the root BRAIN.md.

---

## Update — 2026-09-27 (part 3) — REAL LLM (Gemini) task completed and rendered

A real Gemini API key was wired into the backend (model routing fixed to `gemini-2.5-flash`,
the live successor of the 404'd 1.5/2.5-pro models). E2E with the demo account:
- Task `5fea6283-deaa-44ce-a2d3-a474b691e92b`: **PENDING → RUNNING → COMPLETED in 1m15s**
  with 6 real LLM calls (6 agents, tester/docs parallel), 22,915 tokens, ₹2.33 actual cost,
  quality 0.9, hallucination clean.
- UI renders the REAL result: a complete documented `factorial(n)` implementation shown in
  the Code tab, per-agent cost breakdown, full trace timeline, Output/Code/Docs tabs.
- No frontend changes needed. Console clean (Vite warnings + expected token-refresh 401s).
- Still unverified: Anthropic/OpenAI real calls (no keys); cross-process WebSocket push.

---

## Update — 2026-09-27 (part 2) — RUNNING → COMPLETED now verified in the live UI

Backend added a deterministic fake LLM provider (`LLM_FAKE_MODE=true`, dev-only, refused in
production) and installed litellm. Re-ran the E2E with the demo account:
- Task `9cbcd62b-0e5c-4e73-912d-7eab48d11847`: **PENDING → RUNNING → COMPLETED** in <1s.
- Task detail page renders the full success path: 4 agents started/finished with per-agent
  costs, cost-breakdown table (967 tokens, ₹0.21 actual), summary output panel, quality and
  hallucination scores, "✓ Task complete" trace.
- Console clean apart from Vite warnings and the expected 401→refresh→200 token flow.
- No frontend changes needed — existing success rendering worked on first contact with a
  genuinely COMPLETED task.
- Still unverified: real API-key LLM calls; cross-process WebSocket live push.

Backend: 542 tests passed, mypy clean. NOT production-ready.

---

## Update — 2026-09-27 — REAL task execution verified against the live UI

### What happened:
With the fixed backend stack (broker :6389, real uvicorn :8001, real Celery worker), a task
created through the demo account (`demo@nexusai.local` / `NexusDemo@2026!`) went
**PENDING → RUNNING → FAILED** and the UI rendered the full lifecycle:
- Tasks list: the task appears with status **Failed**, 4 agent icons, 20s duration.
- Task detail page: "Failed" header, agent-activity timeline from real `/trace` data
  (task_started → failure_patterns_checked → routing_complete → cost_estimated →
  planner started → task_failed with the REAL error), "Task failed" card + retry button.
- The failure error shown is the controlled LLM failure: `All LLM providers failed
  (... No module named 'litellm' ...)` — expected; no LLM keys/dependency in this env.
- Console: only Vite/React-Router future-flag warnings and the expected 401 →
  `/auth/refresh` → 200 token-retry flow. No app crashes, no fake success states.

### Frontend changes this round:
NONE — existing error handling (`TaskDetailPage` failed card, `toTaskResult` raw.error
mapping, auth refresh interceptor) already handled the failure path correctly.

### Still unverified:
- WebSocket live push DURING execution from the worker process (traces arrive via WS
  connect replay from DB + polling; cross-process live push needs Redis pub/sub).
- Real LLM streaming (no litellm/keys).
- Frontend tests: none exist (no `test` script in package.json).

Backend verification: 536 pytest passed, mypy clean (95 files). NOT production-ready.

---

---

## Project Identity
- Name: NexusAI Frontend (`nexusai-frontend`)
- Framework: React 18 + Vite 5 + TypeScript 5 (strict)
- Styling: TailwindCSS 3 + CSS custom properties (design tokens)
- State: Zustand (global) + TanStack React Query v5 (server state)
- Real-time: native WebSocket via `WebSocketManager` (`src/lib/websocket.ts`)
- Charts: Recharts 2
- Toasts: react-hot-toast
- Backend API: http://localhost:8000 (all endpoints under `/api/v1/`)
- Package manager: npm (Node 22)

## Running the app
```bash
npm install
npm run dev        # → http://localhost:5173
npm run build      # tsc && vite build
npm run lint       # eslint (flat config)
```
- `.env` ships with `VITE_USE_MOCK=true` → the app runs fully **without the backend**,
  powered by `src/lib/mockApi.ts` + `src/lib/mockData.ts` (real API shapes, fake values).
- Flip `VITE_USE_MOCK=false` to hit the real backend.
- Login: any email/password (mock). Hint shown on the login page: `demo@nexusai.dev`.
- Sessions survive reloads via persisted refreshToken (accessToken is memory-only).

## Design System
Single source of truth: `src/design/tokens.css` (CSS variables), mapped into Tailwind
utilities in `tailwind.config.ts` (e.g. `bg-surface`, `text-brand-light`, `border-border`,
`bg-agent-coder`). Dynamic colors (agent/status) are applied via inline `var(--agent-*)`
styles because Tailwind's JIT cannot see runtime-built class names.

**THEME: "Obsidian & Emerald" — rich dark, emerald + gold, jewel accents (no purple/pink).**
- **Palette**: `--bg-base #070B09` (obsidian green-black) · `--bg-surface #0D1310` · `--bg-elevated #16201A` ·
  `--bg-border #25332B` · brand emerald `#10B981` + gold secondary `#F2CE6B` · status green/amber/red/blue
  kept semantic · agent colors: gold family (coder/planner/docs) + jewel tones (emerald/red/cyan/orange/coral/teal) ·
  cool sage text `#EEF4F0/#A9C0B3/#5C6D63/#6EE7B7`.
- **Type**: Inter (body) + JetBrains Mono (terminal, code, traces) + **Playfair Display**
  (`font-display`) for the brand wordmark and auth hero. Loaded in `index.html`.
- **Effects** (index.css + tailwind keyframes):
  - `body::before` — fixed aurora layer of two slowly drifting gold glows (`aurora-drift`).
  - `.card:hover` — gold border + soft gold glow shadow.
  - `.btn-gold-shine` — sheen sweep across primary buttons on hover; `.btn-gold-live` —
    continuous shimmer (used on the Run Task hero CTA).
  - `.text-gradient-gold` — animated gold gradient text (wordmarks, "always on.").
  - `animate-gold-pulse` — pulsing gold glow utility.
- **Radii**: cards 12px (rounded-card) · buttons/inputs 8px · badges full.
- **Signature element**: `AgentActivityFeed` — terminal-style, color-coded, auto-scrolling
  live event log (timestamp · agent badge · message), driven by WebSocket.
- Mobile-first: bottom `MobileNav` (<md), collapsible `Sidebar` (md+), all pages responsive.
- Reverting to the original indigo theme = restore the old token values in `tokens.css` (and
  the indigo rgba values in `index.css`, `CostPage.tsx` PIE_COLORS, `favicon.svg`).

## Page Registry
| Route | Page | Data source |
|---|---|---|
| `/login` | `LoginPage` | authAPI.login (mock: any creds) |
| `/register` | `RegisterPage` | authAPI.register (auto-login) |
| `/dashboard` | `DashboardPage` | tasks.list, cost.history(daily), live activity feed (WS `__live__` in mock) |
| `/tasks/new` | `NewTaskPage` | cost.estimate (debounced 1s), budget, tasks.create → redirects to detail |
| `/tasks` | `TasksPage` | tasks.list (filters, pagination, cancel modal) |
| `/tasks/:id` | `TaskDetailPage` | tasks.get, tasks.trace, tasks.cost, WS `/ws/{id}`, hitl.pending (panel) |
| `/cost` | `CostPage` | budget, cost.history(period), cost.breakdown, tasks.list (expensive) |
| `/agents` | `AgentsPage` | agents.list (+quality metrics via observability) |
| `/observability` | `ObservabilityPage` | traces (filtered), quality metrics, tasks.list |
| `/memory` | `MemoryPage` | memory.search, memory.failures, memory.clear |
| `/hitl` | `HITLPage` | hitl.pending/history/approve/reject |
| `/settings` | `SettingsPage` | authStore (profile), settingsStore (budget/alerts/currency/notifications), cost.budget |

Protected routes live under `ProtectedLayout` (auth gate + Sidebar/TopBar/MobileNav/Toaster/HitlSync).

## Component Registry
- **ui**: Button, Card, Input, Select, Badge, Modal, Tooltip, Spinner, Skeleton, EmptyState,
  ErrorState, ProgressBar, Toggle, PasswordStrengthMeter, CopyButton
- **layout**: Sidebar (collapsible, HITL badge), TopBar (title, HITL bell, budget pill, user menu),
  PageWrapper, MobileNav (5 items), ConnectionBanner (WS "Reconnecting…"), ProtectedLayout, HitlSync
- **agent**: AgentAvatar, AgentStatusDot, AgentActivityFeed ★, AgentCard, AgentTimeline (parallel groups)
- **task**: TaskCard, TaskStatusBadge (pulse on running), TaskGoalInput (char counter),
  TaskCostPreview (per-agent estimate table + budget remaining), TaskResultPanel (Output/Code/Tests/Docs tabs,
  tiny markdown renderer + lightweight syntax highlighter)
- **cost**: CostMeter (live ticker), CostChart (Recharts, budget-aware bar colors), CostBreakdown, BudgetProgress
- **trace**: TraceEventRow, TraceTimeline (grouped by task, expand/collapse), TraceFilter
- **hitl**: HITLBanner (countdown + approve/reject), HITLModal (confirm), HITLQueue (cards)
- **memory**: MemorySearchBar, MemoryResultCard, FailurePatternCard

## API Integration Map
All defined in `src/lib/api.ts` (real axios + interceptors) with mock-mode swap at the bottom.
Hooks import `auth | tasks | cost | hitl | observability | memory | agents` from `@/lib/api`.

- authAPI: register, login (OAuth2 form), logout, me
- tasksAPI: create, list (status/limit/offset), get, cancel (DELETE), trace, cost
- costAPI: estimate, history (daily/weekly/monthly), breakdown (global|task), budget, setBudget
- hitlAPI: pending, approve, reject, history
- observabilityAPI: traces (task_id/event_type/agent_type), agentMetrics, qualityMetrics
- memoryAPI: search (q,n), failures, clear
- agentsAPI: list, stats

WS protocol: `{ event: <trace_event_type>, data: <TraceEvent> }`; `wsManager.on(taskId, '*', handler)`
receives the flattened event. `traceEventFromWS` in `src/lib/events.ts` rebuilds the TraceEvent
(note: nested `event_data` — fixed 2026-08-10).

## Store map
- `authStore` — user/accessToken(memory)/refreshToken(persisted); session restored on reload from persisted token.
- `taskStore` — activeTaskId, liveEvents (dedup, cap 400), liveCost, liveAgentStatuses.
- `notificationStore` — hitlPendingCount (badges), deduped app notifications, toast cooldown.
- `settingsStore` (persisted) — currency (INR default), monthlyBudgetUsd, budget alerts, notification prefs.
- `uiStore` — sidebar collapsed. `connectionStore` — WS status for the reconnect banner.

## Mock layer (dev-only)
- `mockData.ts` — seeded ~15 tasks (varied statuses incl. 2 running + 1 hitl_waiting), traces,
  cost records, budget, history (7d/8w/6m), model/agent breakdowns, agent metrics, HITL approvals,
  memories, failure patterns, 30-day quality series. Seeded RNG (stable-ish).
- `mockApi.ts` — same request/response shapes as the backend, with latency.
- `mockWs.ts` — MockWebSocket replays a task's remaining "live script" while the page is open;
  `__live__` channel feeds the dashboard feed. HITL approve/reject dispatch follow-up events.
- **Known limitation**: mock tasks only progress while their detail page is open (WS script
  pauses when the socket closes). Acceptable for demo; real backend has no such constraint.

## Decision Log
1. Built at the workspace root (folder name = package.json `name`), not a `nexusai-frontend/` subfolder.
2. Mock mode is default-on so the app demos without the backend; real API code remains intact behind
   the same module interface (`VITE_USE_MOCK`).
3. Dynamic agent/status colors use inline CSS vars (JIT-safe) instead of generated Tailwind classes.
4. Syntax highlighting: lightweight inline regex highlighter (no extra dep). Markdown: tiny built-in
   renderer (headers/tables/code). Both can be upgraded (shiki/prism + react-markdown) if needed.
5. `isAuthenticated` recomputed from persisted refreshToken at store init so hard reloads keep sessions.
6. Bundle is ~923 kB min (recharts-heavy); chunk-split warning only. Code-splitting is a future task.
7. Currency: API stores USD (`cost_usd`); display converts via settingsStore rate (INR ×83 default),
   matching the ₹-first spec while keeping the data shape real.
8. WS payloads carry the full TraceEvent; `traceEventFromWS` extracts the nested `event_data`.
9. Mock live runs persist trace + cost records as they play, so a completed task's detail page
   shows the full feed even after a reload (as long as the page was open during the run).

## Known Issues
- Vite chunk-size warning (single 922 kB bundle) — acceptable for now.
- Mock tasks only run while watched (see Mock layer above).
- `TaskResultPanel` Docs tab renders simplified markdown (tables/headers/code) — not full GFM.
- HITL expiry countdown is display-only in mock (approvals never auto-expire).

## UX Rules Status (spec §UX RULES)
1. Loading states — ✓ (skeletons + button spinners)  2. Human-readable errors — ✓ (`apiErrorMessage`)
3. Empty states with actions — ✓  4. Destructive actions confirm — ✓ (cancel/clear memory/HITL reject)
5. Success toasts — ✓  6. Active nav state — ✓  7. Mobile bottom nav — ✓  8. ₹ formatting — ✓
9. Duration format Xs / Xm Ys — ✓  10. Relative timestamps — ✓  11. Numbers animate — ✓ (CostMeter)
12. Running tasks pulse brand (emerald) — ✓  13. HITL red badge in sidebar+topbar — ✓  14. WS "Reconnecting…" banner — ✓

## Update Log
### Update — 2026-08-10 (Obsidian & Emerald theme)
- Completed: re-themed the UI from gold & black ("Gilded") to "Obsidian & Emerald" — deep green-black
  backgrounds, rich emerald brand with gold secondary accents, jewel-tone agent colors. Purple/pink
  removed everywhere (debugger pink → coral).
- Files modified: `src/design/tokens.css` (full palette), `src/index.css` (aurora, selection, skeleton
  shimmer, grid backdrop, wordmark highlight), `CostPage.tsx` (PIE_COLORS, tab text), `Button.tsx`,
  `AuthShell.tsx`, `MemoryPage.tsx`, `HITLPage.tsx` (dark-on-brand text → deep emerald `#06281c`),
  `public/favicon.svg`, `index.html` (theme-color).
- Key decisions: kept semantic status colors; primary buttons dark-on-emerald; gold retained as
  secondary accent so the existing shine/sheen effects still read correctly.
- Next: verify against real backend; code-splitting.

### Update — 2026-08-10 (Gold & Black theme)
- Completed: re-themed the whole UI to gold & black ("Gilded") with rich effects.
- Files created/modified: `src/design/tokens.css`, `src/index.css`, `tailwind.config.ts`,
  `index.html` (Playfair Display + theme-color), `public/favicon.svg`, `Button.tsx`,
  `NewTaskPage.tsx` (hero shimmer), `Sidebar.tsx` (gold wordmark + active glow),
  `AuthShell.tsx` (display font + gradient hero), `CostPage.tsx` (gold pie colors),
  `DashboardPage.tsx` (fixed Skeleton-in-<p> DOM nesting warning).
- Key decisions: theme driven entirely by CSS tokens (one-file re-theme); kept semantic
  status colors; primary buttons now use dark text on gold for contrast; agent palette is
  gold family + jewel tones for legibility.
- Connected to API: none (pure presentation change).
- Known issues: none new. Bundle warning unchanged.
- Next: verify against real backend; code-splitting.

### Update — 2026-08-10 (buildout + live verification)
- Completed: Steps 0–20; `tsc --noEmit` ✓, `npm run lint` ✓ (0 errors), `npm run build` ✓.
- Live e2e verified in preview: login → dashboard (stats, live feed, chart, recent tasks) →
  new task (debounced estimate) → submit → live run (streaming feed, cost ticker, timeline) →
  auto-completion (result panel, quality, task info) → session persistence across reloads →
  desktop sidebar + mobile bottom-nav layouts.
- Fixes applied during verification:
  - `traceEventFromWS`: read nested `event_data` from WS payloads (was flattening → "0 agents").
  - `applyScriptEvent` now appends events to the stored trace AND creates cost records per
    agent completion, so reloads/refetches show the full feed + cost breakdown.
  - `task_completed` carries a computed duration (was null for new tasks).
  - `generateTaskForGoal` uses the same estimate formula as `costAPI.estimate` (preview
    estimate now matches the live task's).
  - `authStore` restores `isAuthenticated` from the persisted refresh token on init (hard
    reloads keep the session; accessToken stays memory-only).
  - Removed unused imports / lint noise; websocket `SocketLike` uses `any` internally.
- Known issues: see above.
- Next: verify against the real backend at :8000 with VITE_USE_MOCK=false; add route code-splitting.

---

## Update — 2026-09-24 (connected to the real backend)

### What was done
Connected the existing UI to the actual NexusAI backend (FastAPI, `/api/v1`). No page
was rebuilt and no visual language was changed; the work was done in the API layer plus
the few places that held dummy data.

### Key finding
The previous `src/lib/api.ts` "real backend" code had been written against a **guessed**
API — most of its endpoints did not exist. It was rewritten as a layer of **adapters** that
map the real backend payloads onto the exact shapes the components already consume
(the shapes `mockApi.ts` produced), so hooks/stores/pages stayed intact.

| Frontend call | Actual backend endpoint | Notes |
|---|---|---|
| `auth.login` | `POST /auth/login` | OAuth2 form (`username`/`password`), urlencoded |
| `auth.register` | `POST /auth/register` | returns tokens only |
| `auth.me` | `GET /auth/me` | profile fetched after login to build `user` |
| `auth.logout` | `POST /auth/logout` | server-side token blacklist |
| `tasks.create` | `POST /tasks/` | real goal validation + injection scan |
| `tasks.list` | `GET /tasks/` | paged (server caps `limit` at 100) |
| `tasks.get` | `GET /tasks/{id}` (+ `/trace`) | result enriched from the trace |
| `tasks.cancel` | `DELETE /tasks/{id}` | |
| `tasks.trace` | `GET /tasks/{id}/trace` | already the UI's shape, oldest-first |
| `tasks.cost` | `GET /tasks/{id}/cost` (+ `/trace`) | agent type correlated from the trace |
| `cost.estimate` | `POST /cost/estimate` | real routed models + pricing table |
| `cost.history` | `GET /cost/history` | daily rows aggregated per period client-side |
| `cost.breakdown` | `GET /agents/stats` + `/agents/` | per-task variant uses `/tasks/{id}/cost` |
| `cost.budget` | `GET /cost/budget` | `percentage_used`/`days_remaining` derived |
| `cost.setBudget` | — | **no endpoint** → honest `NOT_SUPPORTED` error |
| `hitl.pending` | `GET /tasks/{id}/hitl/pending` | task-scoped; queue assembled from `hitl_waiting` tasks |
| `hitl.approve/reject` | `POST /tasks/{id}/hitl/resolve` | |
| `hitl.history` | `GET /tasks/{id}/hitl/history` | aggregated across recent tasks |
| `memory.search` | `POST /memory/search` | body `{query, collection, n_results}` |
| `memory.failures` | `POST /memory/search` (`failures`) | derived view — no list endpoint exists |
| `memory.clear` | — | **no endpoint** → honest `NOT_SUPPORTED` error |
| `observability.traces` | `GET /observability/traces` | reversed to oldest-first; `agent_type` filtered client-side |
| `observability.agentMetrics` | `GET /agents/` + `/agents/stats` | registry is the source of truth for which agents exist |
| `observability.qualityMetrics` | `GET /observability/metrics` + `/hallucination` (+ tasks) | 30-day series derived from real task rows |
| `agents.list` / `agents.stats` | `GET /agents/` + `/agents/stats` | |
| WS `/ws/{task_id}` | `{event, data, timestamp}` frame | server timestamp now preserved |

### Bugs found and fixed during integration
1. **Naive-UTC timestamps.** The API serialises datetimes without a timezone
   (`2026-09-23T20:35:03.823630`); JS parsed them as *local* time, so a just-created task
   displayed as "about 6 hours ago". All timestamps are now normalised to UTC in the
   adapters — relative times and chart buckets are correct.
2. **Hardcoded dummy data in `CostPage`.** The "Last 3 months" card contained literal
   `₹276.10 / ₹262.90 / ₹245.20` values. Replaced with the real per-month totals aggregated
   from `GET /cost/history` (newest first, "No spend recorded yet" when empty).
3. **Agents page appeared empty.** It listed only agents present in `/agents/stats`, so a
   tenant with no runs saw nothing. It now lists the real `/agents/` registry (all 15
   agents) and attaches measured stats where they exist.
4. **Infinite skeleton on backend error** in the Memory page; both tabs now show an
   `ErrorState` with a retry.
5. **Misleading "0" quality.** A `null` tenant average (no completed work) was rendered as
   `0`; it now renders "—".
6. **Stale "Demo mode" hint** on the login page now only shows when `VITE_USE_MOCK` is on.
7. **6 of 15 backend agents had no UI metadata** — added `refactor`, `summarizer`, `research`,
   `hallucination_detector`, `cost_controller`, `hitl_controller` (icons + new colour tokens).

### Environment
Envs are read with Vite's mechanism; nothing is hardcoded in app code.
- `.env` / `.env.example`: `VITE_USE_MOCK=false`, `VITE_API_BASE_URL`, `VITE_WS_BASE_URL`,
  `VITE_PROXY_TARGET`, `VITE_HITL_TIMEOUT_SECONDS`.
- `vite.config.ts` proxies `/api`, `/ws`, `/health`, `/metrics` to `VITE_PROXY_TARGET`,
  so the app uses same-origin relative URLs in dev (no `localhost` in app code).
- The WebSocket origin falls back to the page origin when `VITE_WS_BASE_URL` is empty.
- No secrets are involved: the JWT secret, DB URL and provider keys are backend-only.

### Verification actually performed
```
npx tsc --noEmit                          → PASS (0 errors)
npm run lint                              → PASS (0 errors, 2 pre-existing warnings)
npm run build                             → PASS (925 kB / 265 kB gzip)
pytest tests/ -q  (backend)               → 527 passed
```
Live, against a running API on :8000 and the Vite dev server on :5173, driven in the
preview browser:
- **Login** → dashboard with the real user (`UI Tester`), real budget `₹0 / ₹8.3k`
  (USD 100 from `GET /cost/budget`), and the real task list. VERIFIED.
- **Session refresh** → on reload, requests 401 → `POST /auth/refresh` → 200 → original
  requests replayed → 200. Access token stays memory-only; refresh token persists. VERIFIED.
- **Task creation** → real `POST /tasks/`, redirected to the real task UUID with the correct
  creation time. VERIFIED.
- **Cost estimate** → `₹1.23` (= `$0.0148` from the backend, cross-checked by hand against
  `POST /cost/estimate`), listing the real routed models. VERIFIED.
- **Tasks list / detail / cost page / agents / observability / memory / HITL** → all render
  real API data with no console errors. VERIFIED.
- **Vite proxy** → all XHRs hit `localhost:5173/api/v1/...` same-origin. VERIFIED.

### Known limitations (NOT verified)
- **Live task execution / agent activity**: tasks stay `pending` because no Celery worker or
  broker was running, so no agents executed and the trace/result/quality panels correctly
  showed their empty states.
- **Real-time WebSocket streaming**: the socket layer was made conformant with the actual
  `{event, data, timestamp}` frame and connects, but **no live event was ever received** —
  no worker produced events. UNVERIFIED.
- **Backend stack used for verification was degraded**: SQLite + in-process fakeredis with
  Celery dispatch stubbed (`scripts/loadtest_server.py`) — *not* Postgres + Redis + a real
  worker. Production-stack connection is UNVERIFIED.
- **ChromaDB-backed memory** returns 500 without the vector store; the UI now surfaces that
  as an error state. Memory search was not verified with real embeddings.
- **`cost.setBudget` and `memory.clear`** have no backend endpoint; both now fail with an
  explicit message instead of pretending.
- **HITL approve/reject** was not exercised end-to-end (no task ever entered
  `hitl_waiting`).
- **Frontend tests**: `package.json` has no `test` script and no test files exist, so there
  was nothing to run.
- The mock layer (`mockApi`, `mockData`, `mockWs`) is still bundled for the
  `VITE_USE_MOCK=true` path — it is not used in live mode, but it does inflate the bundle.
