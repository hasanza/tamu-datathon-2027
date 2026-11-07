"""Task 2.6: an independent oracle. Given the resolved incidents of an event, recompute the expected outcome with plain
loops over the CSV records (no graph, no planner code), so a bug shared by traversal and planner cannot hide.

It checks WHAT must be touched (sets of ids), not WHERE orders land: placement is policy-dependent (SPEC §7) and is
checked for feasibility by the grader instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from control_tower.data.loader import LOANER_TIERS, TIER_RANK, TODAY, World
from control_tower.schemas.incident import IncidentSpec


@dataclass
class Expected:
    moved_pos: set[str] = field(default_factory=set)
    restart: dict[str, int] = field(default_factory=dict)  # PO -> first working-day index it may land on (same plant)
    notified: dict[str, set[str]] = field(default_factory=dict)  # dealer -> customer orders
    loaners: set[str] = field(default_factory=set)
    held_lots: set[str] = field(default_factory=set)
    stopped_vins: set[str] = field(default_factory=set)
    contacted: set[str] = field(default_factory=set)
    escalate: bool = False
    no_writes: bool = False


def expected_for(world: World, specs: list[IncidentSpec], *, actionable: set[str]) -> Expected:
    """`actionable` = incident ids the system decided to act on (the oracle checks the consequences, not that decision)."""
    exp = Expected()
    real = [s for s in specs if s.category != "noise"]
    if not real:
        exp.no_writes = True
        return exp
    cal = world.calendar
    for s in real:
        if s.incident_id not in actionable:
            exp.escalate = True
            continue
        if s.category == "supplier_delay":
            end = cal.on_or_after(s.new_eta)
            end_idx = cal.idx(end) if end else 20
            for po in world.production_orders.values():
                if (
                    po.plant_id == s.plant_id
                    and s.part_id in world.bom[po.model]
                    and s.orig_eta <= po.build_date < s.new_eta
                    and po.build_date >= TODAY
                ):
                    exp.moved_pos.add(po.id)
                    exp.restart[po.id] = end_idx
        elif s.category == "plant_outage":
            nxt = cal.next_working_day(s.outage_end)
            end_idx = cal.idx(nxt) if nxt else 20
            for po in world.production_orders.values():
                if (
                    po.plant_id == s.plant_id
                    and s.outage_start <= po.build_date <= s.outage_end
                    and po.build_date >= TODAY
                ):
                    exp.moved_pos.add(po.id)
                    exp.restart[po.id] = end_idx
        elif s.category == "quality_hold":
            lot = world.lots[s.lot_id]
            exp.held_lots.add(lot.lot_id)
            for v in world.vehicles.values():
                if (
                    v.plant_id == lot.plant_id
                    and lot.first_build_date <= v.build_date <= lot.last_build_date
                    and lot.part_id in world.bom[v.model]
                ):
                    if v.status == "in_stock":
                        exp.stopped_vins.add(v.vin)
                    elif v.status == "sold" and v.customer_id:
                        exp.contacted.add(v.customer_id)
    # dealers and loaners over ALL moved orders of the event together (rules 4 and 5)
    cos = [c for c in world.customer_orders.values() if c.production_order_id in exp.moved_pos]
    for c in cos:
        exp.notified.setdefault(c.dealer_id, set()).add(c.id)
    by_dealer: dict[str, list] = {}
    for c in cos:
        if world.customers[c.customer_id].tier in LOANER_TIERS:
            by_dealer.setdefault(c.dealer_id, []).append(c)
    for dealer, lst in by_dealer.items():
        lst.sort(key=lambda c: (TIER_RANK[world.customers[c.customer_id].tier], c.promised_date, c.id))
        exp.loaners |= {c.id for c in lst[: world.loaner_pool[dealer]]}
    return exp
