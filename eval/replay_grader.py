"""Task 3.3: replay an action_log.jsonl on a fresh copy of the organizers' world and compare with the oracle.

  uv run python eval/replay_grader.py runs/real1/action_log.jsonl --traces traces/real1 [--report eval/reports/real1.md]

For each event: the log is replayed call by call (failed calls are counted, not replayed), then the final world state is
compared with eval/oracle.py's expectation built from the incidents recorded in the trace. Placement of moved orders is
checked for feasibility (capacity, plant builds the model, same-plant day >= restart) because the exact slot is policy.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from control_tower.data.loader import load_world  # noqa: E402
from control_tower.schemas.trace import Trace  # noqa: E402
from control_tower.world.twin import Twin  # noqa: E402
from eval.oracle import expected_for  # noqa: E402


def grade(log_path: Path, traces_dir: Path) -> tuple[list[dict], dict]:
    world = load_world()
    twin = Twin()
    calls: dict[str, list[dict]] = defaultdict(list)
    for line in log_path.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            calls[d["event_id"]].append(d)
    rows: list[dict] = []
    totals: Counter = Counter()
    for tfile in sorted(traces_dir.glob("E-*.json")):
        trace = Trace.model_validate_json(tfile.read_text())
        eid = trace.event_id
        key = f"grade-{eid}"
        failed = 0
        for c in calls.get(eid, []):
            if not c["ok"]:
                failed += 1
                continue
            twin.execute(key, c["tool"], c["args"])
        st = twin.state(key)
        acted = {s.incident_id for s in trace.incidents if s.category != "noise" and s.confidence >= 0.7}
        unclear_ids = {s.incident_id for s in trace.incidents if any(a.blocking for a in s.ambiguities)}
        exp = expected_for(world, trace.incidents, actionable=acted - unclear_ids)

        moved = {
            po
            for po, (plant, idx) in st["loc"].items()
            if (world.production_orders[po].plant_id, world.calendar.idx(world.production_orders[po].build_date))
            != (plant, idx)
        }
        issues: list[str] = []
        if moved != exp.moved_pos:
            issues.append(
                f"moved POs differ: missing {sorted(exp.moved_pos - moved)[:3]} extra {sorted(moved - exp.moved_pos)[:3]}"
            )
        for po in moved & exp.moved_pos:
            plant, idx = st["loc"][po]
            p0 = world.production_orders[po]
            if plant not in world.plant_models or p0.model not in world.plant_models[plant]:
                issues.append(f"{po} moved to {plant} which does not build {p0.model}")
            if plant == p0.plant_id and idx < exp.restart[po]:
                issues.append(f"{po} rescheduled to idx {idx} before restart idx {exp.restart[po]}")
        over = [k for k, v in st["slots"].items() if len(v) > world.plants[k[0]].slots_per_day]
        if over:
            issues.append(f"over-booked slots: {over[:3]}")
        got_notified = {d: set(ids) for d, ids in st["notified"].items() if ids}
        if got_notified != exp.notified:
            issues.append(f"dealer notifications differ ({len(got_notified)} vs {len(exp.notified)} dealers)")
        loaned = set(st["loaned"])
        if loaned != exp.loaners:
            issues.append(
                f"loaners differ: missing {sorted(exp.loaners - loaned)[:3]} extra {sorted(loaned - exp.loaners)[:3]}"
            )
        if set(st["held"]) != exp.held_lots:
            issues.append(f"held lots {sorted(st['held'])} vs {sorted(exp.held_lots)}")
        if set(st["stopped"]) != exp.stopped_vins:
            issues.append(f"stopped VINs differ ({len(st['stopped'])} vs {len(exp.stopped_vins)})")
        if set(st["customers"]) != exp.contacted:
            issues.append(f"contacted customers differ ({len(st['customers'])} vs {len(exp.contacted)})")
        if exp.escalate and not st["escalated"]:
            issues.append("expected an escalation")
        if exp.no_writes and (moved or loaned or st["held"] or st["stopped"] or st["customers"] or got_notified):
            issues.append("write actions on a noise event")
        if not exp.escalate and not exp.no_writes and st["escalated"] and trace.status == "done":
            issues.append("escalated although everything was actionable")
        kinds = {
            c["tool"]
            for c in calls.get(eid, [])
            if c["ok"] and c["tool"] not in {"mes.get_schedule", "crm.loaner_availability", "escalate"}
        }
        if exp.moved_pos or exp.held_lots:
            if len(kinds) < 3:
                issues.append(f"only {len(kinds)} kinds of write action (rule 9): {sorted(kinds)}")
        rows.append(
            {
                "event": eid,
                "category": trace.classification.category,
                "status": trace.status,
                "calls": len(calls.get(eid, [])),
                "failed": failed,
                "issues": issues,
            }
        )
        totals["events"] += 1
        totals["failed_calls"] += failed
        totals["clean"] += not issues and not failed
    return rows, dict(totals)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--traces", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    rows, totals = grade(a.log, a.traces)
    lines = ["| event | category | status | calls | failed | result |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['event']} | {r['category']} | {r['status']} | {r['calls']} | {r['failed']} | {'OK' if not r['issues'] and not r['failed'] else '; '.join(r['issues']) or 'failed calls'} |"
        )
    lines.append(
        f"\n{totals.get('clean', 0)}/{totals.get('events', 0)} events clean, {totals.get('failed_calls', 0)} failed calls"
    )
    out = "\n".join(lines)
    print(out)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(out + "\n")
    return 0 if totals.get("clean") == totals.get("events") else 1


if __name__ == "__main__":
    raise SystemExit(main())
