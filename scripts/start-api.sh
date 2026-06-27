#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.api-runtime"
PID_FILE="$RUNTIME_DIR/api.pid"
LOG_FILE="$RUNTIME_DIR/api.log"
STATUS_FILE="$RUNTIME_DIR/status"
HOST="${API_HOST:-127.0.0.1}"
PORT="${API_PORT:-8000}"
SESSION_NAME="${API_SCREEN_SESSION:-vellum-agent-api}"
PYBIN="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PYBIN" ]]; then
  PYBIN="$(command -v python3 || true)"
fi
if [[ -z "$PYBIN" ]]; then
  echo "error: no python interpreter found (.venv/bin/python or python3)" >&2
  exit 1
fi

mkdir -p "$RUNTIME_DIR"

is_screen_running() {
  command -v screen >/dev/null 2>&1 && screen -list 2>/dev/null | grep -Fq ".${SESSION_NAME}"
}

is_port_running() {
  command -v lsof >/dev/null 2>&1 && [[ -n "$(lsof -ti "tcp:$PORT" 2>/dev/null || true)" ]]
}

if is_port_running; then
  echo "API is already running on port $PORT."
elif is_screen_running; then
  echo "API screen session is already running: $SESSION_NAME."
else
  : > "$LOG_FILE"
  if command -v screen >/dev/null 2>&1; then
    screen -dmS "$SESSION_NAME" bash -lc "cd \"${ROOT_DIR}\" && PYTHONPATH=\"${ROOT_DIR}/backend\" API_HOST=\"${HOST}\" API_PORT=\"${PORT}\" exec \"$PYBIN\" -m uvicorn agent.api:app --host \"${HOST}\" --port \"${PORT}\" >> \"${LOG_FILE}\" 2>&1"
    echo "screen:$SESSION_NAME" > "$PID_FILE"
  else
    cd "$ROOT_DIR"
    PYTHONPATH="$ROOT_DIR/backend" API_HOST="$HOST" API_PORT="$PORT" nohup "$PYBIN" -m uvicorn agent.api:app --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
  fi
fi

for _ in {1..30}; do
  if python3 - "$HOST" "$PORT" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=1) as response:
    if response.status != 200:
        raise SystemExit(1)
PY
  then
    break
  fi
  if [[ -f "$PID_FILE" ]]; then
    marker="$(cat "$PID_FILE")"
    if [[ "$marker" != screen:* ]] && ! kill -0 "$marker" 2>/dev/null; then
      echo "API failed to start. Log:"
      sed -n '1,160p' "$LOG_FILE" 2>/dev/null || true
      exit 1
    fi
  fi
  sleep 0.5
done

if ! python3 - "$HOST" "$PORT" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=1) as response:
    if response.status != 200:
        raise SystemExit(1)
PY
then
  echo "API did not become ready in time. Log:"
  sed -n '1,160p' "$LOG_FILE" 2>/dev/null || true
  exit 1
fi

{
  echo "status=running"
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "url=http://localhost:$PORT"
  echo "screen_session=$SESSION_NAME"
} > "$STATUS_FILE"

echo "Personal Agent API is ready."
echo "URL: http://localhost:$PORT"
echo "Health: http://localhost:$PORT/api/health"
echo "Runtime marker: $STATUS_FILE"
