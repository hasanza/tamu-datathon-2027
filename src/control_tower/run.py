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
import sys
import time
import traceback
from pathlib import Path

import httpx

from control_tower.data.loader import KIT_DIR, REPO_ROOT, load_world
from control_tower.graph.ontology import build_graph
from control_tower.llm.adapter import LEDGER
from control_tower.orchestration.config import agent_config
from control_tower.orchestration.coordinator import Coordinator
from control_tower.planning.policy import Policy
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--event", action="append", default=[], help="event id, repeatable")
    ap.add_argument("--out", default="runs/dev")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--dry-run", action="store_true", help="use the in-process twin instead of the server")
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
    ap.add_argument("--transfer-min-day", choices=["today", "disruption_end"], default="today")
    a = ap.parse_args(argv)
    if not (a.all or a.event):
        ap.error("pass --all or --event E-xx")

    _apply_model_overrides(a.provider, a.model, a.audit_model)
    out = (REPO_ROOT / a.out) if not Path(a.out).is_absolute() else Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    traces_dir = REPO_ROOT / "traces" / out.name
    (out / "events.ndjson").write_text("")
    sink = Sink(out / "events.ndjson")

    world = load_world()
    graph = build_graph(world)
    index = EntityIndex(world)
    twin = Twin()
    if a.dry_run:
        executor = TwinExecutor(out / "action_log.jsonl")
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
    )  # fmt: skip

    print(f"{len(wanted)} event(s) -> {executor.name}; traces in {traces_dir.relative_to(REPO_ROOT)}")
    t0, rows, failed_events = time.perf_counter(), [], 0
    for i, ev in enumerate(wanted):
        if i and a.pace:
            time.sleep(a.pace)
        t_ev = time.perf_counter()
        try:
            tr = coord.handle(ev)
        except Exception:  # never let one event stop the feed
            failed_events += 1
            print(f"{ev['event_id']}: CRASH\n{traceback.format_exc()}", file=sys.stderr)
            continue
        writes = sum(a.writes and bool(a.result and a.result.ok) for a in tr.actions)
        bad = sum(bool(a.result and not a.result.ok and not a.skipped) for a in tr.actions)
        skipped = sum(a.skipped for a in tr.actions)
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
        wall = time.perf_counter() - t_ev
        print(
            f"{tr.event_id}  {tr.status:9} {tr.classification.category:15} conf={tr.classification.confidence:.2f}  calls={len(tr.actions):4} writes={writes:4} failed={bad} skipped={skipped} "
            f"turns={turns} llm={llm_calls} ${tr.llm.total_cost_usd:.4f} {wall:.0f}s"
        )

    LEDGER.write(out / "models.json")
    total_calls = sum(r[4] for r in rows)
    print(f"\n{len(rows)} handled, {failed_events} crashed, {total_calls} tool calls, {sum(r[6] for r in rows)} failed calls, "
          f"{len(LEDGER.calls)} LLM calls (${LEDGER.total_cost_usd}), {time.perf_counter() - t0:.1f}s")  # fmt: skip
    if hasattr(executor, "close"):
        executor.close()
    return 1 if failed_events else 0


if __name__ == "__main__":
    raise SystemExit(main())
