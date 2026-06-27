#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.api-runtime"
PID_FILE="$RUNTIME_DIR/api.pid"
STATUS_FILE="$RUNTIME_DIR/status"
PORT="${API_PORT:-8000}"
SESSION_NAME="${API_SCREEN_SESSION:-vellum-agent-api}"

if command -v screen >/dev/null 2>&1 && screen -list 2>/dev/null | grep -Fq ".${SESSION_NAME}"; then
  screen -S "$SESSION_NAME" -X quit || true
  echo "Stopped API screen session: $SESSION_NAME."
fi

if [[ -f "$PID_FILE" ]]; then
  marker="$(cat "$PID_FILE")"
  if [[ "$marker" != screen:* ]] && kill -0 "$marker" 2>/dev/null; then
    kill "$marker" 2>/dev/null || true
    echo "Stopped Personal Agent API on pid $marker."
  fi
  rm -f "$PID_FILE"
fi

if command -v lsof >/dev/null 2>&1; then
  pids="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
    echo "Stopped process(es) listening on port $PORT."
  fi
fi

if [[ -f "$STATUS_FILE" ]]; then
  rm -f "$STATUS_FILE"
  echo "Personal Agent API stopped."
else
  echo "Personal Agent API was not running."
fi
