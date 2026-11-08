"""Tasks 1.1-1.4, 2.3-2.5 on the real CSVs and the organizers' Enterprise class. Offline, no LLM.

The expected counts are facts about the data (derived in docs/SPEC.md §6), checked here so a regression in the
traversals or planners is caught immediately. They are not read from, nor hard-coded for, any event text.
"""

from datetime import date

import pytest

from control_tower.data.loader import TODAY
from control_tower.graph.ontology import ONTOLOGY, ontology_mermaid, stats
from control_tower.graph.traverse import (
    customer_orders_of,
    find_lots,
    impact_lot,
    impact_outage,
    impact_supplier_delay,
    trace_path,
)
from control_tower.planning.dealer_care import plan_care
from control_tower.planning.quality import plan_quality
from control_tower.planning.supply_chain import SlotBoard, moves_to_actions, plan_moves
from control_tower.world.twin import check_invariants


def _number(actions):
    for i, a in enumerate(actions, 1):
        a.seq = i
    return actions


def test_world_loads_expected_sizes(world):
    assert len(world.production_orders) == 540 and len(world.customer_orders) == 3263
    assert len(world.vehicles) == 5348 and len(world.lots) == 364 and len(world.shipments) == 364
    assert world.calendar.idx(TODAY) == 0 and world.calendar.date_of(19) == date(2027, 4, 2)
    assert world.calendar.next_working_day(date(2027, 3, 12)) == date(2027, 3, 15)  # skips the weekend


def test_graph_has_every_ontology_edge_type(graph):
    s = stats(graph)
    assert s["ProductionOrder"] == 540 and s["Vehicle"] == 5348 and s["Customer"] == 7000
    present = {(graph.nodes[u]["type"], k, graph.nodes[v]["type"]) for u, v, k in graph.edges(keys=True)}
    assert present == set(ONTOLOGY)
    assert "USES_PART" in ontology_mermaid()


def test_supplier_delay_impact_matches_bom_plant_and_dates(graph, world):
    imp = impact_supplier_delay(
        graph, world, plant_id="P_IN", part_id="CAM-360", orig_eta=date(2027, 3, 15), new_eta=date(2027, 3, 18)
    )
    assert imp.shipment_id == "SH-0182"
    assert imp.po_ids == ["PO-0316", "PO-0319", "PO-0322"]  # VOYAGER only: RANGER/NOVA do not use CAM-360
    assert all(world.production_orders[p].plant_id == "P_IN" for p in imp.po_ids)
    assert imp.disruption_end_idx == 8  # new ETA is exclusive: builds may resume on 03-18
    cos = customer_orders_of(graph, world, imp.po_ids)
    assert len(cos) == 26 and len({c.dealer_id for c in cos}) == 14
    assert len(imp.summary_paths) == 3


def test_new_eta_is_exclusive_and_outage_end_is_inclusive(graph, world):
    delay = impact_supplier_delay(
        graph, world, plant_id="P_IN", part_id="CAM-360", orig_eta=date(2027, 3, 15), new_eta=date(2027, 3, 17)
    )
    assert delay.po_ids == ["PO-0316", "PO-0319"]  # 03-17 build is NOT affected when the part arrives 03-17
    outage = impact_outage(graph, world, plant_id="P_TX", start=date(2027, 3, 19), end=date(2027, 3, 22))
    assert len(outage.pos) == 6 and outage.disruption_end_idx == 11  # restart 03-23 (Tuesday)


def test_trace_path_uses_real_edge_directions(graph):
    p = trace_path(graph, ["SH-0182", "CAM-360", "VOYAGER", "PO-0322", "CO-01812", "D01"])
    kinds = [(e.from_, e.to, e.type) for e in p.edges]
    assert ("SH-0182", "CAM-360", "OF_PART") in kinds
    assert ("VOYAGER", "CAM-360", "USES_PART") in kinds  # stored Model -> Part
    assert ("CO-01812", "D01", "SOLD_BY") in kinds


def _full_delay_plan(world, graph, twin, **kw):
    imp = impact_supplier_delay(graph, world, **kw)
    board = SlotBoard(world)
    moves, left = plan_moves(world, board, imp)
    assert not left
    pool = dict(world.loaner_pool)
    actions = moves_to_actions(imp, moves, "T#1") + plan_care(world, moves, pool, incident_id="T#1", cause="test")
    return imp, moves, _number(actions), pool


def test_e12_style_delay_plan_rehearses_with_zero_errors(world, graph, twin):
    imp, moves, actions, _ = _full_delay_plan(
        world, graph, twin, plant_id="P_IN", part_id="CAM-360", orig_eta=date(2027, 3, 15), new_eta=date(2027, 3, 18)
    )
    assert [m.kind for m in moves] == ["reschedule"] * 3
    assert [m.to_date.isoformat() for m in moves] == ["2027-03-18", "2027-03-18", "2027-03-19"]  # 2 free slots/day
    results = twin.rehearse(actions)
    assert all(r.ok for r in results), [r.error for r in results if not r.ok]
    cos = customer_orders_of(graph, world, imp.po_ids)
    problems = check_invariants(actions, allowed_po_ids=set(imp.po_ids), allowed_co_ids={c.id for c in cos})
    assert problems == []
    assert sum(a.tool == "dealer.notify" for a in actions) == 14


def test_outage_with_scarce_slots_forces_transfers(world, graph, twin):
    imp = impact_outage(graph, world, plant_id="P_MS", start=date(2027, 3, 26), end=date(2027, 3, 30))
    board = SlotBoard(world)
    moves, left = plan_moves(world, board, imp)
    assert not left and len(moves) == 9
    kinds = [m.kind for m in moves]
    assert kinds.count("reschedule") == 6 and kinds.count("transfer") == 3  # 3 days x 2 free slots at P_MS
    assert all(m.to_idx >= imp.disruption_end_idx for m in moves if m.kind == "reschedule")
    assert all(m.to_plant != "P_MS" for m in moves if m.kind == "transfer")
    assert all(m.to_plant in world.builders[m.po.model] for m in moves)
    pool = dict(world.loaner_pool)
    actions = _number(
        moves_to_actions(imp, moves, "T#1") + plan_care(world, moves, pool, incident_id="T#1", cause="test")
    )
    assert all(r.ok for r in twin.rehearse(actions))
    # no slot was ever over-booked on the board
    assert all(len(v) <= 5 for v in board.occ.values())


def test_loaner_priority_and_pool_limit(world, graph, twin):
    imp = impact_outage(graph, world, plant_id="P_KY", start=date(2027, 3, 16), end=date(2027, 3, 18))
    board = SlotBoard(world)
    moves, _ = plan_moves(world, board, imp)
    pool = dict(world.loaner_pool)
    actions = plan_care(world, moves, pool, incident_id="T#1", cause="test")
    assigned = [a.args["customer_order_id"] for a in actions if a.tool == "crm.assign_loaner"]
    per_dealer: dict[str, int] = {}
    for co_id in assigned:
        d = world.customer_orders[co_id].dealer_id
        per_dealer[d] = per_dealer.get(d, 0) + 1
        assert world.customers[world.customer_orders[co_id].customer_id].tier in {"Platinum", "Gold"}
    assert all(n <= world.loaner_pool[d] for d, n in per_dealer.items())
    assert all(v >= 0 for v in pool.values())
    # within a dealer, Platinum always precede Gold
    seen_gold: set[str] = set()
    for co_id in assigned:
        co = world.customer_orders[co_id]
        tier = world.customers[co.customer_id].tier
        if tier == "Gold":
            seen_gold.add(co.dealer_id)
        else:
            assert co.dealer_id not in seen_gold
    assert all(r.ok for r in twin.rehearse(_number(moves_to_actions(imp, moves, "T#1") + actions)))


def test_compound_event_shares_slots_and_pools(world, graph, twin):
    board, pool = SlotBoard(world), dict(world.loaner_pool)
    out = impact_outage(graph, world, plant_id="P_TX", start=date(2027, 3, 19), end=date(2027, 3, 22))
    dly = impact_supplier_delay(
        graph, world, plant_id="P_IN", part_id="CHIP-IVI", orig_eta=date(2027, 3, 15), new_eta=date(2027, 3, 19)
    )
    actions, given = [], set()
    for n, imp in enumerate((out, dly), 1):
        moves, left = plan_moves(world, board, imp)
        assert not left
        actions += moves_to_actions(imp, moves, f"C#{n}")
        actions += plan_care(world, moves, pool, incident_id=f"C#{n}", cause="c", loaner_given_to=given)
    actions = _number(actions)
    assert all(r.ok for r in twin.rehearse(actions))
    assert all(len(v) <= 5 for v in board.occ.values()) and all(v >= 0 for v in pool.values())


@pytest.mark.parametrize(
    ("part", "plant", "first", "last", "lot", "vehicles", "stock", "owners"),
    [
        ("CHIP-IVI", "P_MS", date(2027, 2, 25), date(2027, 3, 1), "LOT-0130", 260, 110, 150),
        ("HARN-B", "P_TX", date(2027, 2, 22), date(2027, 2, 24), "LOT-0017", 180, 86, 94),
        ("CHIP-IVI", "P_IN", date(2027, 3, 2), date(2027, 3, 3), "LOT-0191", 116, 40, 76),
    ],
)
def test_quality_impact_and_plan(world, graph, twin, part, plant, first, last, lot, vehicles, stock, owners):
    (found,) = find_lots(world, part_id=part, plant_id=plant, first=first, last=last)
    assert found.lot_id == lot
    imp = impact_lot(graph, world, lot)
    assert len(imp.vehicles) == vehicles
    assert sum(len(v) for v in imp.in_stock_by_dealer.values()) == stock and len(imp.owners) == owners
    actions = _number(plan_quality(world, imp, incident_id="Q#1", reason="test"))
    assert actions[0].tool == "quality.hold_lot"
    assert len(actions) == 1 + len(imp.in_stock_by_dealer) + owners
    results = twin.rehearse(actions)
    assert all(r.ok for r in results), [r.error for r in results if not r.ok][:3]


def test_twin_rejects_a_bad_plan(twin):
    from control_tower.schemas.action import Action

    bad = Action(
        seq=1,
        agent="supply_chain",
        tool="mes.reschedule",
        args={"production_order_id": "PO-0001", "new_date": "2027-03-18"},
        justification="x",
    )
    (r,) = twin.rehearse([bad])  # PO-0001 is already built
    assert not r.ok and "already built" in (r.error or "")
