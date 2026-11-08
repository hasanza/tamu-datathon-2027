"""Facts about what an event actually did, computed from the executed actions only (successful calls).

Used by the coordinator's `finish` tool (factual draft for the explainer) and by the Coordinator when it assembles the
trace: world diff, counterfactual, the minimal graph path for events nothing was done about, the classification.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from control_tower.data.loader import LOANER_TIERS, World
from control_tower.schemas.action import Action
from control_tower.schemas.incident import IncidentSpec
from control_tower.schemas.trace import (
    Classification,
    Counterfactual,
    GraphEdge,
    GraphNode,
    GraphPath,
    MovedPO,
    NotifiedDealer,
    WorldDiff,
)

MOVES = {"mes.reschedule", "mes.transfer"}
_ENTITY_NODE = {"plant": "Plant", "part": "Part", "supplier": "Supplier", "shipment": "Shipment", "lot": "Lot"}


def ok(a: Action) -> bool:
    return bool(a.result and a.result.ok and not a.skipped)


def world_diff(world: World, actions: list[Action]) -> WorldDiff:
    done = [a for a in actions if ok(a)]
    moved = []
    for a in done:
        if a.tool in MOVES:
            po = world.production_orders[a.args["production_order_id"]]
            moved.append(
                MovedPO(
                    production_order_id=po.id,
                    kind="transfer" if a.tool == "mes.transfer" else "reschedule",
                    from_plant=po.plant_id,
                    from_date=po.build_date,
                    to_plant=a.args.get("to_plant_id") or po.plant_id,
                    to_date=a.args["new_date"],
                )
            )
    return WorldDiff(
        moved_pos=moved,
        notified_dealers=[
            NotifiedDealer(dealer_id=a.args["dealer_id"], customer_order_ids=a.args["customer_order_ids"])
            for a in done
            if a.tool == "dealer.notify"
        ],
        loaners=[a.args["customer_order_id"] for a in done if a.tool == "crm.assign_loaner"],
        held_lots=[a.args["lot_id"] for a in done if a.tool == "quality.hold_lot"],
        stopped_vins=[v for a in done if a.tool == "dealer.stop_sale" for v in a.args["vins"]],
        contacted_customers=[a.args["customer_id"] for a in done if a.tool == "crm.notify_customer"],
    )


def counterfactual(world: World, diff: WorldDiff) -> Counterfactual:
    cos = {c.id for m in diff.moved_pos for c in world.cos_by_po.get(m.production_order_id, [])}
    entitled = sum(world.customers[world.customer_orders[c].customer_id].tier in LOANER_TIERS for c in cos)
    slips = [max(0, (m.to_date - m.from_date).days) for m in diff.moved_pos]  # a transfer to an earlier day is no slip
    return Counterfactual(
        customers_affected=len(cos),
        avg_slip_days=round(sum(slips) / len(slips), 1) if slips else None,
        loaners_entitled=entitled,
        loaners_assigned=len(diff.loaners),
        vehicles_pulled=len(diff.stopped_vins),
        owners_contacted=len(diff.contacted_customers),
    )


def minimal_path(world: World, graph: Any, index: Any, event_id: str, text: str, label: str) -> GraphPath:
    """Event -MENTIONS-> every plant / part / supplier / shipment / lot id the text names (possibly none)."""
    nodes = [GraphNode(id=event_id, type="Event", label=label)]
    edges: list[GraphEdge] = []
    for etype, ids in index.scan(text).items():
        ntype = _ENTITY_NODE.get(etype)
        for eid in ids:
            if ntype is None or eid not in graph.nodes:
                continue
            nodes.append(GraphNode(id=eid, type=ntype, label=graph.nodes[eid]["label"]))
            edges.append(GraphEdge(from_=event_id, to=eid, type="MENTIONS"))
    return GraphPath(nodes=nodes, edges=edges)


def classify(specs: list[IncidentSpec], reason: str) -> Classification:
    real = [s for s in specs if s.category != "noise"]
    if not specs:
        return Classification(category="unconfirmed", confidence=0.0, reason=reason)
    if not real:
        return Classification(category="noise", confidence=min(s.confidence for s in specs), reason=reason)
    category = "compound" if len(real) > 1 else real[0].category
    return Classification(category=category, confidence=min(s.confidence for s in real), reason=reason)


def _incs(a: Action) -> list[str]:
    return list(a.incident_ids) or ([a.incident_id] if a.incident_id else [])


def incident_sentence(world: World, spec: IncidentSpec, actions: list[Action]) -> str:
    """One factual sentence for a real incident, counting successful actions only."""
    inc = spec.incident_id
    mine = [a for a in actions if ok(a) and inc in _incs(a)]
    moves = [a for a in mine if a.tool in MOVES]
    t = sum(a.tool == "mes.transfer" for a in moves)
    cos = {c.id for a in moves for c in world.cos_by_po.get(a.args["production_order_id"], [])}
    notified = {a.args["dealer_id"] for a in mine if a.tool == "dealer.notify"}
    loans = sum(a.tool == "crm.assign_loaner" and a.args["customer_order_id"] in cos for a in actions if ok(a))
    if spec.category == "supplier_delay":
        sup = world.suppliers[spec.supplier_id].name if spec.supplier_id else "the supplier"
        part = world.parts[spec.part_id].name if spec.part_id else "a part"
        return (
            f"{sup}'s {part} shipment {spec.shipment_id or ''} to {world.plants[spec.plant_id].name} slips from "
            f"{spec.orig_eta} to {spec.new_eta}. {len(moves)} affected production orders were moved to the earliest "
            f"free slots ({len(moves) - t} rescheduled, {t} transferred); {len(notified)} dealers were each notified "
            f"once for {len(cos)} customer orders; {loans} Platinum/Gold customers received loaners within pool limits."
        )
    if spec.category == "plant_outage":
        return (
            f"{world.plants[spec.plant_id].name} is down {spec.outage_start} to {spec.outage_end}. {len(moves)} "
            f"production orders were moved ({len(moves) - t} rescheduled at the same plant"
            + (f", {t} transferred to other plants because no same-plant slot was free" if t else "")
            + f"); {len(notified)} dealers notified once each for {len(cos)} customer orders; {loans} loaners assigned."
        )
    holds = [a.args["lot_id"] for a in mine if a.tool == "quality.hold_lot"]
    stopped = sum(len(a.args["vins"]) for a in mine if a.tool == "dealer.stop_sale")
    dealers = sum(a.tool == "dealer.stop_sale" for a in mine)
    owners = sum(a.tool == "crm.notify_customer" for a in mine)
    if not holds:
        return f"Quality incident {inc}: no lot was held."
    lot = world.lots[holds[0]]
    return (
        f"Lot {lot.lot_id} ({world.parts[lot.part_id].name} from {world.suppliers[lot.supplier_id].name} at "
        f"{world.plants[lot.plant_id].name}, built {lot.first_build_date} to {lot.last_build_date}) was placed on "
        f"hold. {stopped} unsold vehicles were stopped from sale at {dealers} dealers and {owners} owners of sold "
        "vehicles were contacted."
    )


def tool_counts(actions: list[Action]) -> dict[str, int]:
    return dict(sorted(Counter(a.tool for a in actions if a.writes and ok(a)).items()))
