"""Live runner used by the UI's "Run feed" button (POST /api/run).

  python -m control_tower.live --mode server|dry [--event E-11] [--pace 1.0]
  python -m control_tower.live --custom events.json      # ONE judge-supplied event, private sandbox server

`server` starts a FRESH organizers' enterprise server on a private port (out dir runs/live, so action_log.jsonl is the
submission-format log), runs the pipeline against it, then stops it. `dry` rehearses/executes on the in-process twin only
(no server, no real calls). Traces go to traces/live; the UI/API tail runs/live/events.ndjson.

`--custom` starts a separate PRIVATE organisers' server whose feed is the one custom event (out dir
runs/custom/sandbox/<event_id>, never submitted) and runs the same agents through the same MCP client against it.
Traces go to traces/custom; the stream is runs/custom/events.ndjson.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from control_tower import run
from control_tower.data.loader import KIT_DIR, REPO_ROOT

OUT = "runs/live"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _server(events_file: Path, out: Path):
    """Start a FRESH organisers' enterprise server on a free port; yield its url (None if it never came up)."""
    out.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    server = subprocess.Popen(
        [
            sys.executable, str(KIT_DIR / "enterprise_server.py"), "--data", str(KIT_DIR / "data"),
            "--events", str(events_file), "--out", str(out), "--port", str(port), "--overwrite",
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
            yield None
            return
        yield url
    finally:
        server.terminate()
        server.wait(timeout=5)


def _custom(path: str, run_dir: str = "runs/custom", traces_dir: str = "traces/custom") -> int:
    events = json.loads(Path(path).read_text())
    eid = events[0]["event_id"]
    rd = Path(run_dir) if Path(run_dir).is_absolute() else REPO_ROOT / run_dir
    rd.mkdir(parents=True, exist_ok=True)
    with _server(Path(path).resolve(), rd / "sandbox" / eid) as url:
        if url is None:
            return 2
        return run.main(
            [
                "--all",
                "--events-file",
                path,
                "--server",
                url,
                "--executor",
                "mcp",
                "--out",
                run_dir,
                "--traces-dir",
                traces_dir,
                "--sandbox",
            ]
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["server", "dry"], default="dry")
    ap.add_argument("--event", action="append", default=[])
    ap.add_argument(
        "--custom", help="JSON file with ONE judge-supplied event: run against a private sandbox server via MCP"
    )
    ap.add_argument("--run-dir", default="runs/custom", help="--custom: run dir / stream (default runs/custom)")
    ap.add_argument("--traces-dir", default="traces/custom", help="--custom: trace dir (default traces/custom)")
    ap.add_argument("--parallel", type=int, default=1, help="handle N events at once (default 1)")
    ap.add_argument("--pace", type=float, default=1.0)
    a = ap.parse_args(argv)
    if a.custom:  # own server (fresh world), own run/trace dirs (runs/custom, traces/custom); never touches runs/live
        return _custom(a.custom, a.run_dir, a.traces_dir)
    shutil.rmtree(REPO_ROOT / "traces" / "live", ignore_errors=True)
    (REPO_ROOT / OUT).mkdir(parents=True, exist_ok=True)
    args = ["--out", OUT, "--pace", str(a.pace), "--parallel", str(a.parallel)]
    args += [x for e in a.event for x in ("--event", e)] if a.event else ["--all"]
    if a.mode == "dry":
        return run.main([*args, "--dry-run"])
    with _server(KIT_DIR / "data" / "events.json", REPO_ROOT / OUT) as url:
        if url is None:
            return 2
        return run.main([*args, "--server", url])


if __name__ == "__main__":
    raise SystemExit(main())
