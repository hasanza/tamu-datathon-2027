"""Facts about what an event actually did, computed from the executed actions only (successful calls).

Used by the coordinator's `finish` tool (factual draft for the explainer) and by the Coordinator when it assembles the
trace: world diff, counterfactual, the minimal graph path for events nothing was done about, the classification.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any

from control_tower.data.loader import LOANER_TIERS, World
from control_tower.schemas.action import Action
from control_tower.schemas.incident import IncidentSpec
from control_tower.schemas.trace import (
    Classification,
    Counterfactual,
    Fact,
    GraphEdge,
    GraphNode,
    GraphPath,
    IncidentBrief,
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


def _move_facts(world: World, mine: list[Action], actions: list[Action]) -> tuple[list[Fact], dict[str, Any]]:
    """The three rows shared by outages and delays, plus the counts the sentence needs."""
    moves = [a for a in mine if a.tool in MOVES]
    transfers = [a for a in moves if a.tool == "mes.transfer"]
    t = len(transfers)
    cos = {c.id for a in moves for c in world.cos_by_po.get(a.args["production_order_id"], [])}
    notified = {a.args["dealer_id"] for a in mine if a.tool == "dealer.notify"}
    loans = sum(a.tool == "crm.assign_loaner" and a.args["customer_order_id"] in cos for a in actions if ok(a))
    entitled = sum(world.customers[world.customer_orders[c].customer_id].tier in LOANER_TIERS for c in cos)
    resched = len(moves) - t
    plants = sorted({a.args["to_plant_id"] for a in transfers if a.args.get("to_plant_id")})
    if t:
        detail = f"{resched} rescheduled · {t} transferred to {', '.join(plants)}"
    else:
        where = sorted({world.production_orders[a.args["production_order_id"]].plant_id for a in moves})
        detail = f"{resched} rescheduled at {', '.join(where)}"
    facts = [
        Fact(label="Orders moved", value=str(len(moves)), detail=detail),
        Fact(label="Dealers notified", value=str(len(notified)), detail=f"{len(cos)} customer orders"),
        Fact(label="Loaners", value=str(loans), detail=f"of {entitled} entitled"),
    ]
    return facts, {"moves": len(moves), "t": t, "notified": len(notified), "cos": len(cos), "loans": loans}


def incident_brief(world: World, spec: IncidentSpec, actions: list[Action]) -> IncidentBrief:
    """Fact rows for a real incident, counting successful actions only. `incident_sentence` is derived from this."""
    inc = spec.incident_id
    mine = [a for a in actions if ok(a) and inc in _incs(a)]
    if spec.category in {"supplier_delay", "plant_outage"}:
        facts, _ = _move_facts(world, mine, actions)
        plant = world.plants[spec.plant_id]
        if spec.category == "plant_outage":
            return IncidentBrief(
                incident_id=inc, category=spec.category,
                title=f"Plant outage · {plant.name} ({plant.plant_id})",
                window=f"{spec.outage_start} → {spec.outage_end}", facts=facts,
            )  # fmt: skip
        sup = world.suppliers[spec.supplier_id].name if spec.supplier_id else "the supplier"
        part = world.parts[spec.part_id].name if spec.part_id else "a part"
        return IncidentBrief(
            incident_id=inc, category=spec.category,
            title=f"Supplier delay · {sup} · {spec.part_id} → {plant.name} ({plant.plant_id})",
            window=f"ETA {spec.orig_eta} → {spec.new_eta}",
            facts=[Fact(label="Shipment", value=spec.shipment_id or "", detail=part), *facts],
        )  # fmt: skip
    holds = [a.args["lot_id"] for a in mine if a.tool == "quality.hold_lot"]
    stop = [a for a in mine if a.tool == "dealer.stop_sale"]
    owners = sum(a.tool == "crm.notify_customer" for a in mine)
    if not holds:
        return IncidentBrief(
            incident_id=inc, category=spec.category, title=f"Quality hold · {spec.lot_id or inc}",
            note="no lot was held",
        )  # fmt: skip
    lot = world.lots[holds[0]]
    plant = world.plants[lot.plant_id]
    return IncidentBrief(
        incident_id=inc, category=spec.category,
        title=f"Quality hold · {lot.lot_id} · {lot.part_id} ({world.suppliers[lot.supplier_id].name}) at {plant.name} ({plant.plant_id})",
        window=f"built {lot.first_build_date} → {lot.last_build_date}",
        facts=[
            Fact(label="Lot held", value=lot.lot_id),
            Fact(label="Stop-sales", value=f"{sum(len(a.args['vins']) for a in stop)} VINs", detail=f"at {len(stop)} dealers"),
            Fact(label="Owners contacted", value=str(owners)),
        ],
    )  # fmt: skip


def _mon_day(d: date) -> str:
    return f"{d:%b} {d.day}"


def _range_words(a: str, b: str) -> str:
    x, y = date.fromisoformat(a), date.fromisoformat(b)
    return f"{_mon_day(x)}–{y.day}" if (x.year, x.month) == (y.year, y.month) else f"{_mon_day(x)}–{_mon_day(y)}"


_OPTION = re.compile(r"^(\S+) (\d{4}-\d\d-\d\d)\.\.(\d{4}-\d\d-\d\d)$")


def blocking_ambiguity(spec: IncidentSpec) -> Any:
    return next((a for a in spec.ambiguities if a.blocking), None)


def ambiguity_ids(amb: Any, n: int | None = None) -> list[str]:
    ids = [o.split()[0] for o in amb.options if o.split()]
    return ids[:n] if n else ids


def ambiguity_note(amb: Any) -> str:
    """The blocking ambiguity in plain words, with its options (dates as 'Mon D')."""
    label = amb.field.removesuffix("_id").replace("_", " ").capitalize()
    shown = []
    for o in amb.options:
        m = _OPTION.match(o)
        shown.append(f"{m[1]} ({_range_words(m[2], m[3])})" if m else o)
    issue = amb.issue.rstrip(".")
    if issue.startswith("the stated window overlaps") and shown:
        what = "the stated window overlaps " + (" and ".join(shown) if len(shown) <= 2 else ", ".join(shown))
    else:
        what = issue + (f" (options: {', '.join(shown)})" if shown else "")
    return f"{label} ambiguous: {what}; a human must pick one"


def escalated_brief(world: World, spec: IncidentSpec, text: str) -> IncidentBrief:
    """An escalated incident keeps whatever resolved: same title style as the acted variants, plus the ambiguity."""
    inc, cat = spec.incident_id, spec.category
    amb = blocking_ambiguity(spec) if cat != "unconfirmed" else None
    note = ambiguity_note(amb) if amb else text[:200]
    plant = world.plants.get(spec.plant_id) if spec.plant_id else None
    part = world.parts.get(spec.part_id) if spec.part_id else None
    where = f" at {plant.name} ({plant.plant_id})" if plant else ""
    title, window = None, None
    if cat == "plant_outage" and plant:
        title = f"Plant outage · {plant.name} ({plant.plant_id})"
        if spec.outage_start and spec.outage_end:
            window = f"{spec.outage_start} → {spec.outage_end}"
    elif cat == "supplier_delay" and (plant or part or spec.supplier_id):
        sup = world.suppliers.get(spec.supplier_id) if spec.supplier_id else None
        bits = [x for x in (sup.name if sup else None, spec.part_id) if x]
        title = "Supplier delay · " + " · ".join(bits) + (f" → {plant.name} ({plant.plant_id})" if plant else "")
        if spec.orig_eta and spec.new_eta:
            window = f"ETA {spec.orig_eta} → {spec.new_eta}"
    elif cat == "quality_hold" and (plant or part or spec.supplier_id or spec.lot_id):
        what = f"{part.name} ({part.part_id})" if part else (spec.lot_id or "lot")
        title = f"Quality hold · {what}{where}"
        if spec.build_window_start and spec.build_window_end:
            window = f"built {spec.build_window_start} → {spec.build_window_end}"
    if title is None:
        title = "Unconfirmed · " + (cat.replace("_", " ") if cat != "unconfirmed" else "report")
    return IncidentBrief(incident_id=inc, category=cat, title=title, window=window, note=note)


def entities_of(world: World, spec: IncidentSpec, br: IncidentBrief | None = None) -> list[str]:
    """Display strings the agents inferred for one incident (plant, part, supplier, shipment, lot, window...), in
    first-seen order, de-duplicated, non-empty. With `br` (the incident's brief) the list also takes the strings the
    brief renders from the actions (held lot, window) and keeps only those that appear verbatim in the brief's title,
    window, facts or note, so exact-match bolding finds each of them. Pure: no I/O, no LLM."""
    cand: list[str | None] = []
    plant = world.plants.get(spec.plant_id) if spec.plant_id else None
    part = world.parts.get(spec.part_id) if spec.part_id else None
    sup = world.suppliers.get(spec.supplier_id) if spec.supplier_id else None
    if plant:
        cand += [plant.name, plant.plant_id]
    if part:
        cand += [part.part_id, part.name]
    if sup:
        cand.append(sup.name)
    cand += [spec.shipment_id, spec.lot_id]
    if br:
        cand.append(br.window)
        cand += [f.value for f in br.facts if f.label in {"Lot held", "Shipment"}]
        lot = next((world.lots.get(f.value) for f in br.facts if f.label == "Lot held"), None)
        if lot:
            cand += [lot.lot_id, lot.part_id, world.parts[lot.part_id].name, world.plants[lot.plant_id].name]
            cand += [lot.plant_id, world.suppliers[lot.supplier_id].name]
    amb = blocking_ambiguity(spec) if spec.category != "unconfirmed" else None
    if amb:
        cand += ambiguity_ids(amb)
        cand += [_range_words(m[2], m[3]) for o in amb.options if (m := _OPTION.match(o))]
    if br is None:
        pairs = [(spec.outage_start, spec.outage_end, "{} → {}"), (spec.orig_eta, spec.new_eta, "ETA {} → {}")]
        cand += [fmt.format(a, b) for a, b, fmt in pairs if a and b]
    seen: dict[str, None] = {}
    haystack = ""
    if br:
        haystack = " | ".join(
            [br.title, br.window or "", br.note or ""] + [f"{f.label} {f.value} {f.detail or ''}" for f in br.facts]
        )
    for c in cand:
        if c and (br is None or c in haystack):
            seen.setdefault(c)
    return list(seen)


def incident_sentence(world: World, spec: IncidentSpec, actions: list[Action]) -> str:
    """One factual sentence for a real incident, built from the same `IncidentBrief` rows."""
    br = incident_brief(world, spec, actions)
    inc = spec.incident_id
    if spec.category in {"supplier_delay", "plant_outage"}:
        f = {x.label: x for x in br.facts}
        moves, notified, loans = (int(f[k].value) for k in ("Orders moved", "Dealers notified", "Loaners"))
        cos = int((f["Dealers notified"].detail or "0").split()[0])
        t = (
            int(f["Orders moved"].detail.split("·")[1].split()[0])
            if "transferred" in (f["Orders moved"].detail or "")
            else 0
        )
        if spec.category == "supplier_delay":
            sup = world.suppliers[spec.supplier_id].name if spec.supplier_id else "the supplier"
            part = world.parts[spec.part_id].name if spec.part_id else "a part"
            return (
                f"{sup}'s {part} shipment {spec.shipment_id or ''} to {world.plants[spec.plant_id].name} slips from "
                f"{spec.orig_eta} to {spec.new_eta}. {moves} affected production orders were moved to the earliest "
                f"free slots ({moves - t} rescheduled, {t} transferred); {notified} dealers were each notified "
                f"once for {cos} customer orders; {loans} Platinum/Gold customers received loaners within pool limits."
            )
        return (
            f"{world.plants[spec.plant_id].name} is down {spec.outage_start} to {spec.outage_end}. {moves} "
            f"production orders were moved ({moves - t} rescheduled at the same plant"
            + (f", {t} transferred to other plants because no same-plant slot was free" if t else "")
            + f"); {notified} dealers notified once each for {cos} customer orders; {loans} loaners assigned."
        )
    if not br.facts:
        return f"Quality incident {inc}: no lot was held."
    lot = world.lots[br.facts[0].value]
    stopped = int(br.facts[1].value.split()[0])
    dealers = int((br.facts[1].detail or "0").split()[1])
    owners = br.facts[2].value
    return (
        f"Lot {lot.lot_id} ({world.parts[lot.part_id].name} from {world.suppliers[lot.supplier_id].name} at "
        f"{world.plants[lot.plant_id].name}, built {lot.first_build_date} to {lot.last_build_date}) was placed on "
        f"hold. {stopped} unsold vehicles were stopped from sale at {dealers} dealers and {owners} owners of sold "
        "vehicles were contacted."
    )


def tool_counts(actions: list[Action]) -> dict[str, int]:
    return dict(sorted(Counter(a.tool for a in actions if a.writes and ok(a)).items()))
