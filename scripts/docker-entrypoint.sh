#!/bin/sh
# Hosted image: the pipeline (control_tower.live) and the API's reset/run endpoints write to runs/live and traces/live
# under the repo root. When RUN_DIR / TRACES_DIR point elsewhere (a mounted volume), link those two paths there.
set -e
cd /app
link() { # link <repo-relative path> <target>
  [ -n "$2" ] || return 0
  mkdir -p "$2"
  [ "$(readlink -f "$1")" = "$(readlink -f "$2")" ] && return 0
  rm -rf "$1"; mkdir -p "$(dirname "$1")"; ln -s "$2" "$1"
}
link runs/live "$RUN_DIR"
link traces/live "$TRACES_DIR"
exec uv run --no-sync uvicorn api.app:app --host 0.0.0.0 --port "${PORT:-8080}"
