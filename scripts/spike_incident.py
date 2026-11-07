"""Hour-one spike: impact -> plan -> rehearse on the twin, for one incident given as CLI parameters.

  uv run python scripts/spike_incident.py delay  --plant P_IN --part CAM-360 --orig 2027-03-15 --new 2027-03-18
  uv run python scripts/spike_incident.py outage --plant P_MS --start 2027-03-26 --end 2027-03-30
  uv run python scripts/spike_incident.py lot    --part CHIP-IVI --plant P_MS --first 2027-02-25 --last 2027-03-01
Parameters are what the understanding layer will produce later; nothing here is tied to a specific event.
"""

import argparse
from collections import Counter
from datetime import date

from control_tower.agents.dealer_care import plan_care
from control_tower.agents.policy import Policy
from control_tower.agents.quality import plan_quality
from control_tower.agents.supply_chain import SlotBoard, moves_to_actions, plan_moves
from control_tower.data.loader import load_world
from control_tower.graph.ontology import build_graph, stats
from control_tower.graph.traverse import (
    customer_orders_of,
    find_lots,
    impact_lot,
    impact_outage,
    impact_supplier_delay,
)
from control_tower.world.twin import Twin, check_invariants


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["delay", "outage", "lot"])
    ap.add_argument("--plant", required=True)
    ap.add_argument("--part")
    ap.add_argument("--orig", type=date.fromisoformat)
    ap.add_argument("--new", type=date.fromisoformat)
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--first", type=date.fromisoformat)
    ap.add_argument("--last", type=date.fromisoformat)
    ap.add_argument("--transfer-min-day", choices=["today", "disruption_end"], default="today")
    a = ap.parse_args()
    policy = Policy(transfer_min_day=a.transfer_min_day)

    world = load_world()
    g = build_graph(world)
    print("graph:", stats(g))
    twin = Twin()

    if a.kind == "lot":
        (lot,) = find_lots(world, part_id=a.part, plant_id=a.plant, first=a.first, last=a.last)
        imp = impact_lot(g, world, lot.lot_id)
        print(
            f"{lot.lot_id}: {len(imp.vehicles)} vehicles from {len(imp.pos)} POs; "
            f"{sum(len(v) for v in imp.in_stock_by_dealer.values())} unsold at {len(imp.in_stock_by_dealer)} dealers; "
            f"{len(imp.owners)} owners"
        )
        actions = plan_quality(world, imp, incident_id="S#1", reason="supplier quality alert")
        allowed_po, allowed_co, real = set(), set(), True
    else:
        if a.kind == "delay":
            imp = impact_supplier_delay(g, world, plant_id=a.plant, part_id=a.part, orig_eta=a.orig, new_eta=a.new)
            print(f"shipment: {imp.shipment_id}")
        else:
            imp = impact_outage(g, world, plant_id=a.plant, start=a.start, end=a.end)
        board, pool = SlotBoard(world), dict(world.loaner_pool)
        moves, left = plan_moves(world, board, imp, policy)
        cos = customer_orders_of(g, world, imp.po_ids)
        print(
            f"affected POs: {len(imp.pos)} | customer orders: {len(cos)} | dealers: {len({c.dealer_id for c in cos})}"
            f" | unplaceable: {len(left)}"
        )
        for m in moves:
            print(f"  {m.po.id} {m.po.model} {m.po.build_date} -> {m.kind} {m.to_plant} {m.to_date}")
        actions = moves_to_actions(imp, moves, "S#1") + plan_care(
            world, moves, pool, incident_id="S#1", cause=f"{a.kind} at {a.plant}", policy=policy
        )
        allowed_po, allowed_co, real = set(imp.po_ids), {c.id for c in cos}, True

    for i, act in enumerate(actions, 1):
        act.seq = i
    results = twin.rehearse(actions)
    failed = [(x, r) for x, r in zip(actions, results, strict=True) if not r.ok]
    print("actions:", dict(Counter(x.tool for x in actions)), "total", len(actions))
    print(f"rehearsal: {len(actions) - len(failed)} ok, {len(failed)} failed")
    for x, r in failed[:5]:
        print("  FAIL", x.tool, x.args, "->", r.error)
    if a.kind != "lot":
        problems = check_invariants(actions, allowed_po_ids=allowed_po, allowed_co_ids=allowed_co, real_incident=real)
        print("invariants:", problems or "ok")


if __name__ == "__main__":
    main()
