"""Live runner used by the UI's "Run feed" button (POST /api/run).

  python -m control_tower.live --mode server|dry [--event E-11] [--pace 1.0]

`server` starts a FRESH organizers' enterprise server on a private port (out dir runs/live, so action_log.jsonl is the
submission-format log), runs the pipeline against it, then stops it. `dry` rehearses/executes on the in-process twin only
(no server, no real calls). Traces go to traces/live; the UI/API tail runs/live/events.ndjson.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time

import httpx

from control_tower import run
from control_tower.data.loader import KIT_DIR, REPO_ROOT

OUT = "runs/live"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["server", "dry"], default="dry")
    ap.add_argument("--event", action="append", default=[])
    ap.add_argument("--pace", type=float, default=1.0)
    a = ap.parse_args(argv)
    shutil.rmtree(REPO_ROOT / "traces" / "live", ignore_errors=True)
    (REPO_ROOT / OUT).mkdir(parents=True, exist_ok=True)
    args = ["--out", OUT, "--pace", str(a.pace)]
    args += [x for e in a.event for x in ("--event", e)] if a.event else ["--all"]
    if a.mode == "dry":
        return run.main([*args, "--dry-run"])
    port = _free_port()
    server = subprocess.Popen(
        [
            sys.executable, str(KIT_DIR / "enterprise_server.py"), "--data", str(KIT_DIR / "data"),
            "--events", str(KIT_DIR / "data" / "events.json"), "--out", str(REPO_ROOT / OUT),
            "--port", str(port), "--overwrite",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{url}/events", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            print("enterprise server did not start", file=sys.stderr)
            return 2
        return run.main([*args, "--server", url])
    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
