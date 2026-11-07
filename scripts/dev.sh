#!/usr/bin/env bash
# One command to use the project through the UI:  scripts/dev.sh
# API on :8001 (shows the committed 15-event snapshot until you press "Run feed"), UI on http://localhost:5173
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d ui/node_modules ] || (cd ui && npm install)
export TRACES_DIR="${TRACES_DIR:-traces/snapshot}" RUN_DIR="${RUN_DIR:-runs/dev}"
uv run uvicorn api.app:app --port 8001 &
API=$!
trap 'kill $API 2>/dev/null' EXIT
cd ui && npm run dev -- --open
