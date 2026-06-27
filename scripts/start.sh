#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.ui-runtime"
PID_FILE="$RUNTIME_DIR/ui.pid"
LOG_FILE="$RUNTIME_DIR/ui.log"
STATUS_FILE="$RUNTIME_DIR/status"
HOST="${UI_HOST:-127.0.0.1}"
PORT="${UI_PORT:-4242}"

mkdir -p "$RUNTIME_DIR"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "UI is already running on pid $(cat "$PID_FILE")."
else
  ROOT_DIR="$ROOT_DIR" UI_HOST="$HOST" UI_PORT="$PORT" node <<'NODE' > "$LOG_FILE" 2>&1 &
const http = require('http');
const fs = require('fs/promises');
const path = require('path');

const root = process.env.ROOT_DIR;
const host = process.env.UI_HOST || '127.0.0.1';
const port = Number(process.env.UI_PORT || 4242);

const types = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.jsx', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.md', 'text/markdown; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.webp', 'image/webp'],
  ['.ico', 'image/x-icon'],
]);

function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

function apiStub(req, res, pathname) {
  if (pathname === '/api/status') return json(res, 200, { ok: true, name: 'Vellum UI', mode: 'static' });
  if (pathname === '/api/files') return json(res, 200, { files: [] });
  if (pathname === '/api/chats') return json(res, 200, { chats: [] });
  if (pathname === '/api/settings') return json(res, 200, {});
  if (pathname === '/api/providers') return json(res, 200, { providers: [], preferred: null });
  if (pathname === '/api/connectors') return json(res, 200, { servers: [] });
  if (pathname === '/api/memory-files') return json(res, 200, {});
  return json(res, 501, { error: 'Only the static UI is available in this trimmed workspace.' });
}

async function serve(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname.startsWith('/api/')) return apiStub(req, res, url.pathname);

  const requestPath = url.pathname === '/' ? '/frontend/ui/vellum-chat.html' : decodeURIComponent(url.pathname);
  const filePath = path.resolve(root, `.${requestPath}`);
  if (!filePath.startsWith(root + path.sep)) return json(res, 403, { error: 'Forbidden' });

  try {
    const data = await fs.readFile(filePath);
    res.writeHead(200, { 'Content-Type': types.get(path.extname(filePath)) || 'application/octet-stream' });
    res.end(data);
  } catch (error) {
    json(res, error.code === 'ENOENT' ? 404 : 500, { error: error.code === 'ENOENT' ? 'Not found' : error.message });
  }
}

http.createServer(serve).listen(port, host, () => {
  console.log(`Vellum UI listening at http://${host === '127.0.0.1' ? 'localhost' : host}:${port}`);
});
NODE
  echo "$!" > "$PID_FILE"
fi

{
  echo "status=running"
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "url=http://localhost:$PORT"
} > "$STATUS_FILE"

echo "Vellum UI is ready."
echo "URL: http://localhost:$PORT"
echo "Runtime marker: $STATUS_FILE"
