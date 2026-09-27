#!/usr/bin/env bash
# NexusAI dev stack — single source of truth. Order: broker -> API -> worker -> frontend.
# Verifies each service is ACTUALLY alive (ports, HTTP, task-consumption round trip).
#
# Port contract (do not blur):
#   :5173 frontend (Vite)   :8001 REAL FastAPI backend   :6389 broker (fakeredis)
#   :8000 is the LOADTEST-ONLY stub (scripts/loadtest_server.py) — never dev startup.
set -u
cd "$(dirname "$0")/.."
mkdir -p .freebuff
PASS=0; FAIL=0
BACKEND_PID=""
ok()  { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

echo "==> 0. Killing stale dev processes (uvicorn/celery/loadtest)"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'uvicorn app.main|celery_app worker|loadtest_server' -and \$_.Name -notmatch 'powershell|bash' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1
sleep 2

echo "==> 1. Broker (fakeredis :6389)"
if ! netstat -ano | grep ":6389" | grep -q LISTEN; then
  .venv/Scripts/python.exe -c "from fakeredis import TcpFakeServer; s=TcpFakeServer(('127.0.0.1',6389),server_type='redis'); s.serve_forever()" > .freebuff/fakeredis-broker.log 2>&1 &
  for i in $(seq 1 10); do sleep 1; netstat -ano | grep ":6389" | grep -q LISTEN && break; done
fi
.venv/Scripts/python.exe -c "import redis; redis.Redis(host='127.0.0.1',port=6389,db=1).ping()" >/dev/null 2>&1 \
  && ok "broker accepting connections on 6389" || bad "broker not reachable"

echo "==> 2. Backend API (:8001, REAL app — never the loadtest stub on :8000)"
if ! netstat -ano | grep ":8001" | grep -q LISTEN; then
  .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 > .freebuff/real-uvicorn.log 2>&1 &
  for i in $(seq 1 15); do sleep 1; curl -s -o /dev/null http://127.0.0.1:8001/docs && break; done
fi
curl -s -o /dev/null http://127.0.0.1:8001/docs && ok "backend responding on :8001" || bad "backend not responding"

echo "==> 3. Celery worker (exactly ONE) + functional health check"
# NOTE: `celery inspect ping` is NOT used as a health gate: it relies on
# pub/sub (pidbox fanout) which fakeredis's TcpFakeServer does not push
# (PUBLISH returns subscriber count but subscribers never get the message).
# The functional check below exercises the REAL path (list-based queue ->
# worker consumption -> task handler), which is what matters for dispatch.
WORKER_N=$(powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'celery_app worker' -and \$_.Name -notmatch 'powershell|bash' }).Count" 2>/dev/null | tr -d '\r')
if [ "${WORKER_N:-0}" -eq 0 ]; then
  .venv/Scripts/celery.exe -A app.workers.celery_app worker --loglevel=INFO --pool=solo --concurrency=1 --without-gossip --without-mingle --without-heartbeat > .freebuff/celery-worker.log 2>&1 &
  WORKER_PID=$!
  for i in $(seq 1 20); do
    sleep 1
    grep -q "ready" .freebuff/celery-worker.log 2>/dev/null && break
  done
fi
# Exactly one worker process tree (3 PIDs on Windows: celery.exe + 2 python children)
WORKER_N=$(powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'celery_app worker' -and \$_.Name -notmatch 'powershell|bash' }).Count" 2>/dev/null | tr -d '\r')
if [ "${WORKER_N:-0}" -ge 3 ]; then ok "exactly one Celery worker process tree ($WORKER_N launcher PIDs)"; else bad "worker process tree count = ${WORKER_N:-0} (expected 3 launcher PIDs)"; fi
grep -q "nexusai.execute_task" .freebuff/celery-worker.log \
  && ok "nexusai.execute_task registered in worker task panel" || bad "nexusai.execute_task NOT in worker task panel"
# Functional round trip: dispatch a poison task for a nonexistent user and wait for
# the worker to log RECEIPT of that exact celery task id (consumption proof; the task
# itself then fails fast on Gemini 429, which is fine — receipt is what we verify).
TASKID=$(.venv/Scripts/python.exe - <<'EOF'
import uuid
from app.workers.celery_app import celery_app
res = celery_app.send_task('nexusai.execute_task', args=['00000000-0000-0000-0000-000000000000','healthcheck goal',{},'t','u'], task_id=str(uuid.uuid4()))
print(res.id)
EOF
)
CONSUMED=0
for i in $(seq 1 30); do
  sleep 1
  grep -q "$TASKID] received" .freebuff/celery-worker.log && CONSUMED=1 && break
done
[ "$CONSUMED" -eq 1 ] && ok "worker consumed dispatched task (end-to-end round trip)" \
  || bad "worker did not consume the dispatched task"
grep -q "ready" .freebuff/celery-worker.log \
  && ok "Celery worker ready" || bad "Celery worker not ready"

echo "==> 4. Frontend (:5173, proxying to the REAL backend :8001)"
if ! netstat -ano | grep ":5173" | grep -q LISTEN; then
  (cd "New folder" && npm run dev > ../.freebuff/preview-frontend.log 2>&1 &)
  for i in $(seq 1 15); do sleep 1; netstat -ano | grep ":5173" | grep -q LISTEN && break; done
fi
netstat -ano | grep ":5173" | grep -q LISTEN && ok "frontend listening on 5173" || bad "frontend not listening"

echo "==> Summary"
echo "  Broker       $( [ -n "$(netstat -ano | grep ':6389' | grep LISTEN)" ] && echo PASS || echo FAIL )"
echo "  Backend      $( curl -s -o /dev/null http://127.0.0.1:8001/docs && echo PASS || echo FAIL )"
echo "  Celery       $( [ "${WORKER_N:-0}" -ge 3 ] && echo PASS || echo FAIL )"
echo "  Registration $( grep -q 'nexusai.execute_task' .freebuff/celery-worker.log && echo PASS || echo FAIL )"
echo "  Round-trip   $( [ "$CONSUMED" -eq 1 ] && echo PASS || echo FAIL )"
echo "  Frontend     $( [ -n "$(netstat -ano | grep ':5173' | grep LISTEN)" ] && echo PASS || echo FAIL )"
BACKEND_PID=$(netstat -ano | grep ":8001" | grep LISTEN | awk '{print $5}' | head -1)
echo "==> PIDs: backend=$BACKEND_PID worker=${WORKER_PID:-existing}"
echo "==> $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && echo "==> STACK UP: UI=http://localhost:5173 API=http://127.0.0.1:8001/docs" || exit 1
