"""Run the control tower over the event feed.

  uv run python -m control_tower.run --all --out runs/dev --server http://127.0.0.1:8000
  uv run python -m control_tower.run --event E-12 --dry-run --out runs/dry       # no server: the twin plays the enterprise

Artifacts: <out>/action_log.jsonl (written by the server, or by the dry-run executor), <out>/models.json,
<out>/events.ndjson (live stream for the UI), and traces/<run name>/<event_id>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from control_tower.data.loader import KIT_DIR, REPO_ROOT, load_world
from control_tower.graph.ontology import build_graph
from control_tower.llm.adapter import LEDGER
from control_tower.orchestration.config import agent_config
from control_tower.orchestration.coordinator import Coordinator
from control_tower.planning.policy import Policy
from control_tower.schemas.trace import Trace
from control_tower.trace import Sink
from control_tower.understanding.resolve import EntityIndex
from control_tower.world.executor import HttpExecutor, McpExecutor, TwinExecutor
from control_tower.world.twin import Twin


def load_events(server: str | None) -> list[dict]:
    if server:
        return httpx.get(f"{server}/events", timeout=30).raise_for_status().json()
    return json.loads((KIT_DIR / "data" / "events.json").read_text())


def _apply_model_overrides(provider: str | None, model: str | None, audit_model: str | None) -> None:
    """--provider/--model apply to every agent through the CT_MODEL_<AGENT> env overrides of agents.toml."""
    if provider or model:
        for agent in ("coordinator", "supply_chain_planner", "dealer_network", "customer_care_quality", "auditor"):
            cfg = agent_config(agent)
            os.environ[f"CT_MODEL_{agent.upper()}"] = f"{provider or cfg.provider}/{model or cfg.model}"
    if audit_model:
        os.environ["CT_MODEL_AUDITOR"] = audit_model


ABORT_AFTER = 2  # consecutive provider-failed events that stop a run


def _provider_failed(tr: Trace | None) -> bool:
    return bool(getattr(getattr(tr, "orchestration", None), "provider_failure", False))


def run_feed(
    handle: Callable[[dict], Trace],
    events: list[dict],
    *,
    parallel: int = 1,
    pace: float = 0.0,
    announce: Callable[[dict], None] | None = None,
    stagger: tuple[float, float] = (0.5, 1.2),
) -> list[tuple[dict, Trace | None, str, float]]:
    """Handle `events`; returns (event, trace or None, traceback, wall seconds) IN EVENT ORDER.
    parallel > 1 runs that many events at once (each has its own EventContext and its own world on the enterprise);
    one event crashing never stops the others. After ABORT_AFTER consecutive events (in processing order) that ended
    with a provider failure the run stops: no further event is started (events already running finish), so the
    result may be shorter than `events`.

    `announce(event)` is called right before each event is handled (the arrival lead-in). In parallel runs the first
    `parallel` workers are staggered: worker i waits i * uniform(*stagger) seconds first, so arrivals read as a stream."""

    def one(ev: dict, slot: int = 0) -> tuple[dict, Trace | None, str, float]:
        if announce and slot and stagger[1] > 0:
            time.sleep(slot * random.uniform(*stagger))
        t0 = time.perf_counter()
        try:
            if announce:
                announce(ev)  # lead-in sleep is not part of the event's wall time
            t0 = time.perf_counter()
            return ev, handle(ev), "", time.perf_counter() - t0
        except Exception:  # never let one event stop the feed
            return ev, None, traceback.format_exc(), time.perf_counter() - t0

    out: list[tuple[dict, Trace | None, str, float]] = []
    streak = 0

    def note(r: tuple[dict, Trace | None, str, float]) -> bool:
        nonlocal streak
        out.append(r)
        streak = streak + 1 if _provider_failed(r[1]) else 0
        return streak >= ABORT_AFTER

    if parallel <= 1:
        for i, ev in enumerate(events):
            if i and pace:
                time.sleep(pace)
            if note(one(ev)):
                break
        return out
    with ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="event") as pool:
        futures = [pool.submit(one, ev, i if i < parallel else 0) for i, ev in enumerate(events)]
        stop = False
        for f in futures:
            if stop:
                if not f.cancel():  # already running: let it finish and keep its result
                    note(f.result())
                continue
            stop = note(f.result())
    return out


def make_announcer(sink: Sink, lead: float) -> Callable[[dict], None] | None:
    """Arrival lead-in: emit `event_incoming`, then wait lead*uniform(0.8, 1.4) s so the UI can show its loader before
    `event_received`. lead <= 0 emits with no sleep and no jitter. None when the sink has no file."""
    if not sink.path:
        return None

    def announce(ev: dict) -> None:
        sink.emit("event_incoming", ev["event_id"], {"received_at": ev.get("received_at"), "source": ev.get("source")})
        if lead > 0:
            time.sleep(lead * random.uniform(0.8, 1.4))

    return announce


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--event", action="append", default=[], help="event id, repeatable")
    ap.add_argument("--out", default="runs/dev")
    ap.add_argument(
        "--action-log", help="dry-run: where the twin executor writes the log (default <out>/action_log.jsonl)"
    )
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="use the in-process sandbox copy of the enterprise instead of a server (developers)",
    )
    ap.add_argument(
        "--sandbox", action="store_true", help="the server is a private sandbox, not the scored one (judge events)"
    )
    ap.add_argument(
        "--executor", choices=["mcp", "http"], default="mcp", help="server mode: MCP client (default) or direct HTTP"
    )
    ap.add_argument("--provider", help="override the provider of every agent (default: agents.toml)")
    ap.add_argument("--model", help="override the model of every agent (default: agents.toml)")
    ap.add_argument("--audit-model", help="override the auditor's model (default: agents.toml [auditor])")
    ap.add_argument("--no-audit", action="store_true")
    ap.add_argument("--no-explain", action="store_true")
    ap.add_argument("--events-file", help="JSON list of events to run instead of the organizers' feed (sandbox runs)")
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to wait between events (live demo)")
    ap.add_argument(
        "--parallel", type=int, default=1, metavar="N", help="handle N events at once (default 1 = sequential)"
    )
    ap.add_argument(
        "--lead",
        type=float,
        default=1.0,
        help="seconds between event_incoming and event_received (jittered 0.8-1.4x; 0 = none)",
    )
    ap.add_argument("--traces-dir", help="where traces are written (default: traces/<name of --out>)")
    ap.add_argument("--transfer-min-day", choices=["today", "disruption_end"], default="today")
    a = ap.parse_args(argv)
    if not (a.all or a.event):
        ap.error("pass --all or --event E-xx")
    if a.parallel < 1:
        ap.error("--parallel must be >= 1")

    _apply_model_overrides(a.provider, a.model, a.audit_model)
    out = (REPO_ROOT / a.out) if not Path(a.out).is_absolute() else Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    traces_dir = (
        (REPO_ROOT / a.traces_dir if not Path(a.traces_dir).is_absolute() else Path(a.traces_dir))
        if a.traces_dir
        else REPO_ROOT / "traces" / out.name
    )
    (out / "events.ndjson").write_text("")
    sink = Sink(out / "events.ndjson")

    world = load_world()
    graph = build_graph(world)
    index = EntityIndex(world)
    twin = Twin()
    if a.dry_run:
        executor = TwinExecutor(Path(a.action_log) if a.action_log else out / "action_log.jsonl")
    elif a.executor == "http":
        executor = HttpExecutor(a.server)
    else:
        executor = McpExecutor(a.server)
    events = (
        json.loads(Path(a.events_file).read_text()) if a.events_file else load_events(None if a.dry_run else a.server)
    )
    wanted = [e for e in events if a.all or e["event_id"] in set(a.event)]
    coord = Coordinator(
        world, graph, index, twin, executor, traces_dir=traces_dir, sink=sink,
        policy=Policy(transfer_min_day=a.transfer_min_day), use_tiebreak=True, use_audit=not a.no_audit, use_explain=not a.no_explain,
        mode="parallel" if a.parallel > 1 else "sequential", target="dry" if a.dry_run else "sandbox" if a.sandbox else "scored",
    )  # fmt: skip

    print(f"{len(wanted)} event(s) -> {executor.name} [{coord.mode} x{a.parallel}]; traces in {traces_dir}")
    t0, rows, failed_events = time.perf_counter(), [], 0
    results = run_feed(
        coord.handle, wanted, parallel=a.parallel, pace=a.pace, announce=make_announcer(sink, a.lead),
        stagger=(0.5, 1.2) if a.lead > 0 else (0.0, 0.0),
    )  # fmt: skip
    for ev, tr, tb, wall in results:
        if tr is None:
            failed_events += 1
            print(f"{ev['event_id']}: CRASH\n{tb}", file=sys.stderr)
            continue
        writes = sum(x.writes and bool(x.result and x.result.ok) for x in tr.actions)
        bad = sum(bool(x.result and not x.result.ok and not x.skipped) for x in tr.actions)
        skipped = sum(x.skipped for x in tr.actions)
        turns = sum(s.kind == "thought" for r in tr.agents for s in r.steps)
        llm_calls = sum(c.attempts for c in tr.llm.calls)
        rows.append(
            (
                tr.event_id,
                tr.status,
                tr.classification.category,
                tr.classification.confidence,
                len(tr.actions),
                writes,
                bad,
            )
        )
        print(
            f"{tr.event_id}  {tr.status:9} {tr.classification.category:15} conf={tr.classification.confidence:.2f}  calls={len(tr.actions):4} writes={writes:4} failed={bad} skipped={skipped} "
            f"turns={turns} llm={llm_calls} ${tr.llm.total_cost_usd:.4f} {wall:.0f}s"
        )  # fmt: skip

    LEDGER.write(out / "models.json")
    total_calls = sum(r[4] for r in rows)
    print(f"\n{len(rows)} handled, {failed_events} crashed, {total_calls} tool calls, {sum(r[6] for r in rows)} failed calls, "
          f"{len(LEDGER.calls)} LLM calls (${LEDGER.total_cost_usd}), {time.perf_counter() - t0:.1f}s")  # fmt: skip
    if hasattr(executor, "close"):
        executor.close()
    if len(results) < len(wanted):
        head = next((r[1].decision_reason for r in reversed(results) if _provider_failed(r[1])), "")[:200]
        print(
            f"ABORTED: LLM provider unavailable on {ABORT_AFTER} consecutive events ({head}); "
            f"{len(wanted) - len(results)} of {len(wanted)} events not run; check the Gemini quota and re-run with --event ...",
            file=sys.stderr,
        )
        return 2
    return 1 if failed_events else 0


if __name__ == "__main__":
    raise SystemExit(main())
