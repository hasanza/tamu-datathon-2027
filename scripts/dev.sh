#!/usr/bin/env bash
# One command to use the project through the UI:  scripts/dev.sh
# API on :8001 (shows the committed 15-event snapshot until you press "Run feed"), UI on http://localhost:5173
set -uo pipefail
cd "$(dirname "$0")/.."
for port in 8001 5173; do
  if lsof -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use. Stop whatever holds it (lsof -iTCP:$port -sTCP:LISTEN) and run again." >&2
    exit 1
  fi
done
[ -d ui/node_modules ] || (cd ui && npm install)
export TRACES_DIR="${TRACES_DIR:-traces/snapshot}" RUN_DIR="${RUN_DIR:-runs/dev}"
uv run uvicorn api.app:app --host 127.0.0.1 --port 8001 &
API=$!
trap 'kill $API 2>/dev/null; pkill -P $API 2>/dev/null' EXIT INT TERM
for _ in $(seq 1 40); do
  curl -sf http://127.0.0.1:8001/api/kpis >/dev/null && break
  kill -0 $API 2>/dev/null || { echo "API failed to start (see output above)." >&2; exit 1; }
  sleep 0.5
done
echo "API ready on :8001. Starting UI on :5173 ..."
cd ui && npm run dev -- --strictPort --open
