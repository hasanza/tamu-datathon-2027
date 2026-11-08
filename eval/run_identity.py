"""Identity check (PLAN_V2 section 9): the same feed K times on fresh enterprise servers must give identical actions.

  uv run python eval/run_identity.py --k 3                              # full feed, 3 runs, sequential
  uv run python eval/run_identity.py --k 2 --events E-01 E-02 E-05      # a subset (cheaper)

Each run starts its own enterprise server on a free port, runs the pipeline through the MCP executor into
runs/identity/k<n>/ (traces in traces/k<n>/), and stops the server. Then, per event, the (tool, args) multiset of the
non-read actions is compared across the runs and against traces/final (the v1 run). Prints a table plus LLM calls, cost,
wall time per run and correction rounds per event. Exit code 1 on any difference or crashed run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "hack_the_highway"
READS = {"mes.get_schedule", "crm.loaner_availability"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def multiset(trace: dict) -> Counter:
    """(tool, canonical args) of every non-read, non-skipped action of a trace dict."""
    return Counter(
        (a["tool"], json.dumps(a["args"], sort_keys=True))
        for a in trace["actions"]
        if a["tool"] not in READS and not a.get("skipped")
    )


def load_traces(d: Path, ids: list[str]) -> dict[str, dict]:
    return {e: json.loads((d / f"{e}.json").read_text()) for e in ids if (d / f"{e}.json").exists()}


def one_run(n: int, events: list[str] | None, parallel: int, extra: list[str]) -> tuple[int, float, Path]:
    out = REPO / "runs" / "identity" / f"k{n}"
    traces = REPO / "traces" / f"k{n}"
    shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(traces, ignore_errors=True)
    out.mkdir(parents=True)
    port = free_port()
    server = subprocess.Popen(
        [
            sys.executable, str(KIT / "enterprise_server.py"), "--data", str(KIT / "data"),
            "--events", str(KIT / "data" / "events.json"), "--out", str(out), "--port", str(port), "--overwrite",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                if httpx.get(f"{url}/events", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise RuntimeError("enterprise server did not start")
        cmd = [sys.executable, "-m", "control_tower.run", "--out", str(out), "--server", url, "--executor", "mcp"]
        cmd += ["--parallel", str(parallel), *extra]
        cmd += [x for e in events for x in ("--event", e)] if events else ["--all"]
        t0 = time.perf_counter()
        with open(out / "run.log", "w") as log:
            rc = subprocess.run(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT).returncode  # noqa: S603
        return rc, time.perf_counter() - t0, traces
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k", type=int, default=3, help="number of runs")
    ap.add_argument("--events", nargs="+", help="event ids (default: the whole feed)")
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--baseline", default=str(REPO / "traces" / "final"), help="v1 traces to compare with")
    ap.add_argument("--compare-only", action="store_true", help="do not run; compare existing runs/identity/k<n>")
    a, extra = ap.parse_known_args(argv)
    ids = a.events or [e["event_id"] for e in json.loads((KIT / "data" / "events.json").read_text())]

    runs: list[dict] = []
    failed_runs = 0
    for n in range(1, a.k + 1):
        if a.compare_only:
            rc, secs, tdir = 0, 0.0, REPO / "traces" / f"k{n}"
        else:
            print(f"run {n}/{a.k} ...", flush=True)
            rc, secs, tdir = one_run(n, a.events, a.parallel, extra)
        failed_runs += rc != 0
        tr = load_traces(tdir, ids)
        calls = sum(c.get("attempts", 1) for t in tr.values() for c in t["llm"]["calls"])
        cost = sum(t["llm"]["total_cost_usd"] for t in tr.values())
        runs.append({"traces": tr, "secs": secs, "calls": calls, "cost": cost, "rc": rc})
        print(f"  run {n}: rc={rc} {len(tr)}/{len(ids)} traces, {calls} LLM calls, ${cost:.4f}, {secs:.0f}s")

    base = load_traces(Path(a.baseline), ids)
    diffs = 0
    print(f"\n{'event':6} {'status per run':30} {'actions':>8} {'across runs':>12} {'vs v1':>7} {'rounds':>8}")
    for e in ids:
        ts = [r["traces"].get(e) for r in runs]
        if any(t is None for t in ts):
            print(f"{e:6} MISSING in run(s) {[i + 1 for i, t in enumerate(ts) if t is None]}")
            diffs += 1
            continue
        sets = [multiset(t) for t in ts]
        same = all(s == sets[0] for s in sets)
        v1 = "n/a" if e not in base else ("same" if multiset(base[e]) == sets[0] else "DIFF")
        diffs += (not same) + (v1 == "DIFF")
        rounds = "/".join(str(t.get("orchestration", {}).get("correction_rounds", 0)) for t in ts)
        print(
            f"{e:6} {'/'.join(t['status'] for t in ts):30} {sum(sets[0].values()):8} "
            f"{'identical' if same else 'DIFF':>12} {v1:>7} {rounds:>8}"
        )
        if not same or v1 == "DIFF":
            ref = sets[0] if same else next(s for s in sets if s != sets[0])
            other = multiset(base[e]) if v1 == "DIFF" and same else sets[0]
            for k_, c in list((ref - other).items())[:3]:
                print(f"         only in first side: {k_[0]} {k_[1][:100]} x{c}")
            for k_, c in list((other - ref).items())[:3]:
                print(f"         only in second side: {k_[0]} {k_[1][:100]} x{c}")
    print()
    for i, r in enumerate(runs, 1):
        print(f"run {i}: {r['calls']} LLM calls, ${r['cost']:.4f}, {r['secs']:.0f}s, rc={r['rc']}")
    print(f"total ${sum(r['cost'] for r in runs):.4f}; {diffs} difference(s), {failed_runs} run(s) with a nonzero exit")
    return 1 if diffs or failed_runs else 0


if __name__ == "__main__":
    raise SystemExit(main())
