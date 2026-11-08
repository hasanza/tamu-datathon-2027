"""Live runner used by the UI's "Run feed" button (POST /api/run).

  python -m control_tower.live --mode server|dry [--event E-11] [--pace 1.0]
  python -m control_tower.live --custom events.json      # ONE judge-supplied event, private sandbox server

A partial run (one or more --event) never wipes the rest: it keeps traces/live, runs against a server whose out dir is
runs/live/partial/<utc ts>, then merges that action_log into runs/live/action_log.jsonl (rows of the re-run events are
replaced) and sums its models.json into runs/live/models.json. A full run (--all) starts fresh.

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
from datetime import UTC, datetime
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


def _merge_action_log(partial: Path, live: Path, event_ids: set[str]) -> None:
    """Replace the rows of `event_ids` in the live log by the partial run's rows (lines kept byte-identical)."""
    kept = []
    if live.exists():
        for line in live.read_text().splitlines():
            try:
                if json.loads(line).get("event_id") in event_ids:
                    continue
            except json.JSONDecodeError:
                pass
            kept.append(line)
    new = partial.read_text().splitlines() if partial.exists() else []
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text("".join(f"{ln}\n" for ln in [*kept, *(x for x in new if x.strip())]))


def _merge_models(old: dict | None, new: dict | None) -> dict | None:
    """Sum calls / tokens / cost per model of two ledger files (models.json format)."""
    if not old or not new:
        return new or old
    by = {f"{m['provider']}/{m['model']}": dict(m) for m in old.get("models", [])}
    for m in new.get("models", []):
        k = f"{m['provider']}/{m['model']}"
        if k in by:
            for f in ("calls", "input_tokens", "output_tokens"):
                by[k][f] = by[k].get(f, 0) + m.get(f, 0)
            by[k]["cost_usd"] = round(by[k].get("cost_usd", 0) + m.get("cost_usd", 0), 6)
        else:
            by[k] = dict(m)
    total = round(old.get("total_cost_usd", 0) + new.get("total_cost_usd", 0), 6)
    return {"models": list(by.values()), "total_cost_usd": total}


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


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
    partial = bool(a.event)  # a partial run merges into runs/live; only a full run (--all) starts fresh
    if not partial:
        shutil.rmtree(REPO_ROOT / "traces" / "live", ignore_errors=True)
    live = REPO_ROOT / OUT
    live.mkdir(parents=True, exist_ok=True)
    args = ["--out", OUT, "--traces-dir", "traces/live", "--pace", str(a.pace), "--parallel", str(a.parallel)]
    args += [x for e in a.event for x in ("--event", e)] if partial else ["--all"]
    part_dir = live / "partial" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    old_models = _read_json(live / "models.json") if partial else None
    try:
        if a.mode == "dry":
            if partial:
                args += ["--action-log", str(part_dir / "action_log.jsonl")]
                part_dir.mkdir(parents=True, exist_ok=True)
            rc = run.main([*args, "--dry-run"])
        else:
            server_out = part_dir if partial else live
            with _server(KIT_DIR / "data" / "events.json", server_out) as url:
                if url is None:
                    return 2
                rc = run.main([*args, "--server", url])
        if partial:
            _merge_action_log(part_dir / "action_log.jsonl", live / "action_log.jsonl", set(a.event))
            merged = _merge_models(old_models, _read_json(live / "models.json"))
            if merged is not None:
                (live / "models.json").write_text(json.dumps(merged, indent=2) + "\n")
        return rc
    finally:
        if partial:
            shutil.rmtree(part_dir, ignore_errors=True)
            with contextlib.suppress(OSError):
                (live / "partial").rmdir()


if __name__ == "__main__":
    raise SystemExit(main())
