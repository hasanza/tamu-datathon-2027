"""Handbook validators V1..V8 (docs/PLAN_V2.md §4). Plain code, no LLM.

Each validator recomputes the expectation from the resolved IncidentSpec with the deterministic planners and the graph
traversals, independently of what the agents passed to their tools, and compares it with the accumulated plan.
A specialist that handed a tool an incomplete or padded list is therefore caught here.

  V1 affected set is exactly the traversal result (rules 1, 2)        V5 quality: hold, stop-sales, owners (rule 6)
  V2 every affected PO moved once, to the earliest feasible slot (3)  V6 nothing outside the affected set (rule 10)
  V3 one dealer.notify per dealer, exactly its orders (rule 4)        V7 >= 3 kinds of write per real incident (9, warning)
  V4 loaners: entitled, in priority order, within the pool (rule 5)   V8 noise / unconfirmed / escalated: no writes (7, 8)
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Collection, Iterable
from typing import Any, Literal

import networkx as nx
from pydantic import BaseModel

from control_tower.data.loader import World
from control_tower.graph.traverse import QualityImpact, find_lots, impact_lot, impact_outage, impact_supplier_delay
from control_tower.planning.dealer_care import plan_care
from control_tower.planning.policy import DEFAULT_POLICY, Policy
from control_tower.planning.supply_chain import Move, SlotBoard, plan_moves
from control_tower.schemas.action import WRITE_TOOLS, Action
from control_tower.schemas.incident import IncidentSpec

MOVE_TOOLS = {"mes.reschedule", "mes.transfer"}
DISRUPTIONS = {"supplier_delay", "plant_outage"}


class Finding(BaseModel):
    incident_id: str | None
    rule: str  # "V1".."V8"
    expected: Any
    got: Any
    severity: Literal["blocking", "warning"] = "blocking"
    handbook_rule: int | None = None

    def short(self) -> str:
        return f"{self.rule}[{self.severity}] {self.incident_id}: expected {self.expected} got {self.got}"


def _incs(a: Action) -> list[str]:
    return list(a.incident_ids) or ([a.incident_id] if a.incident_id else [])


def _key(a: Action) -> tuple:
    """Identity of a write for the V6 sweep (free-text messages excluded)."""
    t, g = a.tool, a.args
    if t in MOVE_TOOLS:
        return (t, g["production_order_id"], g.get("to_plant_id"), g["new_date"])
    if t == "dealer.notify":
        return (t, g["dealer_id"], tuple(sorted(g["customer_order_ids"])))
    if t == "dealer.stop_sale":
        return (t, g["dealer_id"], tuple(sorted(g["vins"])))
    if t == "crm.assign_loaner":
        return (t, g["customer_order_id"])
    if t == "crm.notify_customer":
        return (t, g["customer_id"])
    return (t, json.dumps(g, sort_keys=True, default=str))


def _expected_move_key(m: Move) -> tuple:
    if m.kind == "reschedule":
        return ("mes.reschedule", m.po.id, None, m.to_date.isoformat())
    return ("mes.transfer", m.po.id, m.to_plant, m.to_date.isoformat())


def validate(
    world: World,
    graph: nx.MultiDiGraph,
    incidents: dict[str, IncidentSpec],
    actions: Iterable[Action],
    *,
    escalated: Collection[str] = (),
    pools: dict[str, int] | None = None,
    policy: Policy = DEFAULT_POLICY,
) -> list[Finding]:
    """`incidents` are all resolved incidents of the event in text order; `escalated` the ones the coordinator
    escalated (they, like noise and unconfirmed ones, must have no writes). `pools` = live loaner pools (default: the
    table). Only writes are checked; reads and `escalate` are ignored."""
    writes = [a for a in actions if a.tool in WRITE_TOOLS]
    out: list[Finding] = []
    flagged: set[int] = set()  # id() of actions already reported by V1-V5/V8

    def add(inc: str | None, rule: str, hb: int, expected: Any, got: Any, sev: str = "blocking") -> None:
        out.append(Finding(incident_id=inc, rule=rule, expected=expected, got=got, severity=sev, handbook_rule=hb))  # type: ignore[arg-type]

    esc = set(escalated)
    real = {i: s for i, s in incidents.items() if i not in esc and s.category in DISRUPTIONS | {"quality_hold"}}

    # ---- expectations (independent of the agents) ----
    board = SlotBoard(world)
    exp_moves: dict[str, list[Move]] = {}
    exp_unplaced: dict[str, list[str]] = {}
    for inc, s in real.items():
        if s.category == "supplier_delay":
            impact = impact_supplier_delay(
                graph,
                world,
                plant_id=s.plant_id,
                part_id=s.part_id,
                orig_eta=s.orig_eta,
                new_eta=s.new_eta,
                shipment_id=s.shipment_id,
            )
        elif s.category == "plant_outage":
            impact = impact_outage(graph, world, plant_id=s.plant_id, start=s.outage_start, end=s.outage_end)
        else:
            continue
        moves, left = plan_moves(world, board, impact, policy)
        exp_moves[inc], exp_unplaced[inc] = moves, [p.id for p in left]
    all_moves = [m for ms in exp_moves.values() for m in ms]
    po_inc = {m.po.id: inc for inc, ms in exp_moves.items() for m in ms}
    exp_keys: set[tuple] = {_expected_move_key(m) for m in all_moves}
    first_inc = next(iter(real), None)

    # ---- V1 / V2: moves ----
    got_moves = [a for a in writes if a.tool in MOVE_TOOLS]
    got_by_po: dict[str, list[Action]] = defaultdict(list)
    for a in got_moves:
        got_by_po[a.args["production_order_id"]].append(a)
    for inc, ms in exp_moves.items():
        want = {m.po.id for m in ms}
        missing = sorted(want - set(got_by_po))
        if missing:
            add(inc, "V1", 1, f"move {len(want)} affected POs", f"missing {missing}")
        bad = []
        for m in ms:
            acts = got_by_po.get(m.po.id)
            if not acts:
                continue
            if len(acts) > 1:
                bad.append({"po": m.po.id, "problem": f"moved {len(acts)} times"})
                flagged.update(id(a) for a in acts)
            elif _key(acts[0]) != _expected_move_key(m):
                bad.append({"po": m.po.id, "expected": list(_expected_move_key(m)[2:]), "got": list(_key(acts[0])[2:])})
                flagged.add(id(acts[0]))
        if bad:
            add(
                inc, "V2", 3, "earliest feasible slot per PO (same plant at/after restart, else earliest transfer)", bad
            )
    extra = sorted(set(got_by_po) - set(po_inc))
    if extra:
        owners_of = {po: (_incs(got_by_po[po][0]) or [first_inc])[0] for po in extra}
        for inc in dict.fromkeys(owners_of.values()):
            pos = [p for p in extra if owners_of[p] == inc]
            add(inc, "V1", 1, "only the affected POs", f"also moves unaffected {pos}")
        for po in extra:
            flagged.update(id(a) for a in got_by_po[po])

    # ---- V3: notices ----
    exp_notices = plan_care(world, all_moves, {}, incident_id=None, cause="", policy=policy, include_loaners=False)
    exp_by_dealer = {a.args["dealer_id"]: sorted(a.args["customer_order_ids"]) for a in exp_notices}
    exp_keys |= {_key(a) for a in exp_notices}
    got_notices: dict[str, list[Action]] = defaultdict(list)
    for a in writes:
        if a.tool == "dealer.notify":
            got_notices[a.args["dealer_id"]].append(a)

    def dealer_inc(dealer: str) -> str | None:
        cos = exp_by_dealer.get(dealer) or []
        return po_inc.get(world.customer_orders[cos[0]].production_order_id) if cos else first_inc

    for dealer, want in exp_by_dealer.items():
        acts = got_notices.get(dealer, [])
        if not acts:
            add(dealer_inc(dealer), "V3", 4, f"one dealer.notify for {dealer} listing {want}", "no notice")
            continue
        if len(acts) > 1:
            add(dealer_inc(dealer), "V3", 4, f"exactly one notice for {dealer}", f"{len(acts)} notices")
            flagged.update(id(a) for a in acts)
            continue
        got = sorted(acts[0].args["customer_order_ids"])
        if got != want:
            add(dealer_inc(dealer), "V3", 4, f"{dealer}: {want}", got)
            flagged.add(id(acts[0]))
    for dealer in sorted(set(got_notices) - set(exp_by_dealer)):
        add(first_inc, "V3", 4, "no notice (dealer has no affected order)", f"notice to {dealer}")
        flagged.update(id(a) for a in got_notices[dealer])

    # ---- V4: loaners ----
    exp_loans = plan_care(
        world,
        all_moves,
        dict(pools if pools is not None else world.loaner_pool),
        incident_id=None,
        cause="",
        policy=policy,
        loaner_given_to=set(),
        include_notices=False,
    )
    exp_keys |= {_key(a) for a in exp_loans}
    exp_co = {a.args["customer_order_id"] for a in exp_loans}
    got_loan_acts = [a for a in writes if a.tool == "crm.assign_loaner"]
    got_co = [a.args["customer_order_id"] for a in got_loan_acts]
    by_dealer_missing: dict[str, list[str]] = defaultdict(list)
    for co in sorted(exp_co - set(got_co)):
        by_dealer_missing[world.customer_orders[co].dealer_id].append(co)
    for cos in by_dealer_missing.values():
        add(
            po_inc.get(world.customer_orders[cos[0]].production_order_id, first_inc),
            "V4",
            5,
            f"loaners for {cos}",
            "missing",
        )
    by_dealer_extra: dict[str, list[str]] = defaultdict(list)
    for co in sorted(set(got_co) - exp_co):
        co_row = world.customer_orders.get(co)
        by_dealer_extra[co_row.dealer_id if co_row else "?"].append(co)
    for d, cos in by_dealer_extra.items():
        add(
            first_inc,
            "V4",
            5,
            "only entitled orders, in priority order, within the pool",
            f"extra loaners at {d}: {cos}",
        )
    dup = sorted({c for c in got_co if got_co.count(c) > 1})
    if dup:
        add(first_inc, "V4", 5, "one loaner per customer order", f"duplicates {dup}")
    flagged.update(
        id(a)
        for a in got_loan_acts
        if a.args["customer_order_id"] not in exp_co or got_co.count(a.args["customer_order_id"]) > 1
    )

    # ---- V5: quality ----
    for inc, s in real.items():
        if s.category != "quality_hold":
            continue
        lot_id = s.lot_id
        if lot_id is None and s.part_id and s.plant_id:
            lots = find_lots(
                world, part_id=s.part_id, plant_id=s.plant_id, first=s.build_window_start, last=s.build_window_end
            )
            lot_id = lots[0].lot_id if len(lots) == 1 else None
        if lot_id is None:
            add(inc, "V5", 6, "a resolvable lot", "lot not resolved", "warning")
            continue
        q: QualityImpact = impact_lot(graph, world, lot_id)
        mine = [a for a in writes if inc in _incs(a)]
        holds = [a for a in mine if a.tool == "quality.hold_lot"]
        exp_keys.add(("quality.hold_lot", json.dumps({"lot_id": lot_id})))
        if [a.args["lot_id"] for a in holds] != [lot_id]:
            add(inc, "V5", 6, f"hold {lot_id}", [a.args["lot_id"] for a in holds] or "no hold")
        flagged.update(id(a) for a in holds if a.args["lot_id"] != lot_id)
        stops = {}
        for a in mine:
            if a.tool == "dealer.stop_sale":
                stops.setdefault(a.args["dealer_id"], []).append(a)
        exp_stop = {d: sorted(v) for d, v in q.in_stock_by_dealer.items()}
        exp_keys |= {("dealer.stop_sale", d, tuple(v)) for d, v in exp_stop.items()}
        got_stop = {d: sorted(v for a in acts for v in a.args["vins"]) for d, acts in stops.items()}
        if got_stop != exp_stop or any(len(v) > 1 for v in stops.values()):
            missing_d = sorted(set(exp_stop) - set(got_stop))
            wrong = {
                d: {"expected": exp_stop[d], "got": got_stop[d]}
                for d in exp_stop
                if d in got_stop and got_stop[d] != exp_stop[d]
            }
            extra_d = sorted(set(got_stop) - set(exp_stop))
            add(inc, "V5", 6, "stop-sale of exactly the in-stock affected VINs, one per dealer",
                {"missing_dealers": missing_d, "wrong_vins": wrong, "extra_dealers": extra_d})  # fmt: skip
            flagged.update(id(a) for d in wrong.keys() | set(extra_d) for a in stops.get(d, []))
        notes = [a for a in mine if a.tool == "crm.notify_customer"]
        exp_keys |= {("crm.notify_customer", c) for c in q.owners}
        got_c = [a.args["customer_id"] for a in notes]
        if sorted(got_c) != sorted(q.owners):
            add(inc, "V5", 6, f"one contact per owner ({len(q.owners)} owners)",
                {"missing": sorted(set(q.owners) - set(got_c)), "extra": sorted(set(got_c) - set(q.owners)),
                 "duplicates": sorted({c for c in got_c if got_c.count(c) > 1})})  # fmt: skip
            flagged.update(
                id(a) for a in notes if a.args["customer_id"] not in q.owners or got_c.count(a.args["customer_id"]) > 1
            )

    # ---- V8: no writes for noise / unconfirmed / escalated incidents ----
    quiet = {i for i, s in incidents.items() if i in esc or s.category in {"noise", "unconfirmed"}}
    for inc in sorted(quiet):
        bad = [a for a in writes if inc in _incs(a)]
        if bad:
            add(
                inc,
                "V8",
                7 if incidents[inc].category == "noise" else 8,
                "no write tool calls",
                sorted({a.tool for a in bad}),
            )
            flagged.update(id(a) for a in bad)

    # ---- V6: anything else outside the expected set ----
    stray = [a for a in writes if id(a) not in flagged and _key(a) not in exp_keys]
    if stray:
        add(
            first_inc,
            "V6",
            10,
            "only actions on the affected set",
            [{"tool": a.tool, "args": a.args} for a in stray[:5]],
        )

    # ---- V7: completeness (warning) ----
    for inc in real:
        kinds = {a.tool for a in writes if inc in _incs(a)}
        if len(kinds) < 3:
            add(inc, "V7", 9, ">= 3 different kinds of write action", sorted(kinds), "warning")
    return out


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "blocking"]
