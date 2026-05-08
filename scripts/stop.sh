#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.ui-runtime"
PID_FILE="$RUNTIME_DIR/ui.pid"
STATUS_FILE="$RUNTIME_DIR/status"
PORT="${UI_PORT:-4242}"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "Stopped Vellum UI on pid $pid."
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
  echo "Vellum UI stopped."
else
  echo "Vellum UI was not running."
fi
