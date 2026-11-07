"""Task 1.2: the ontology as a typed property graph (networkx MultiDiGraph) plus exports.

Node ids are the raw business ids (PO-0316, CO-01812, D01, SH-0182, LOT-0130, VIN, ...), unique across types.
Edge key == edge type (see control_tower.schemas.trace.EdgeType); every edge carries ``type``.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from control_tower.data.loader import World

# (from type, edge type, to type): the ontology schema, also rendered as a diagram.
ONTOLOGY: list[tuple[str, str, str]] = [
    ("Supplier", "SUPPLIES", "Part"),
    ("Shipment", "OF_PART", "Part"),
    ("Shipment", "TO_PLANT", "Plant"),
    ("Shipment", "FROM", "Supplier"),
    ("Model", "USES_PART", "Part"),
    ("Plant", "BUILDS_MODEL", "Model"),
    ("ProductionOrder", "AT_PLANT", "Plant"),
    ("ProductionOrder", "OF_MODEL", "Model"),
    ("ProductionOrder", "ON_DAY", "Day"),
    ("CustomerOrder", "FULFILLED_BY", "ProductionOrder"),
    ("CustomerOrder", "SOLD_BY", "Dealer"),
    ("CustomerOrder", "FOR", "Customer"),
    ("Lot", "OF_PART", "Part"),
    ("Lot", "AT_PLANT", "Plant"),
    ("Lot", "FROM", "Supplier"),
    ("Vehicle", "BUILT_BY", "ProductionOrder"),
    ("Vehicle", "AT_DEALER", "Dealer"),
    ("Vehicle", "OWNED_BY", "Customer"),
]


def build_graph(world: World) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()

    def node(nid: str, ntype: str, label: str, **attrs: object) -> None:
        g.add_node(nid, type=ntype, label=label, **attrs)

    def edge(u: str, etype: str, v: str) -> None:
        g.add_edge(u, v, key=etype, type=etype)

    for s in world.suppliers.values():
        node(s.supplier_id, "Supplier", s.name, city=s.city)
    for p in world.parts.values():
        node(p.part_id, "Part", p.name, category=p.category)
    for m, seg in world.models.items():
        node(m, "Model", m.title(), segment=seg)
    for pl in world.plants.values():
        node(pl.plant_id, "Plant", pl.name, slots_per_day=pl.slots_per_day)
    for d in world.calendar.working_days(world.calendar.date_of(-10), world.calendar.date_of(19)):
        node(d.isoformat(), "Day", d.strftime("%a %m-%d"), idx=world.calendar.idx(d))
    for dl in world.dealers.values():
        node(dl.dealer_id, "Dealer", f"{dl.name} ({dl.city})", region=dl.region)
    for c in world.customers.values():
        node(c.customer_id, "Customer", f"{c.tier} customer {c.customer_id}", tier=c.tier)

    supplies: set[tuple[str, str]] = set()
    for s in world.shipments.values():
        node(
            s.shipment_id,
            "Shipment",
            f"{s.shipment_id} · {s.part_id} → {s.plant_id} · ETA {s.eta_date:%m-%d}",
            eta_date=s.eta_date.isoformat(),
            plant_id=s.plant_id,
            part_id=s.part_id,
        )
        edge(s.shipment_id, "OF_PART", s.part_id)
        edge(s.shipment_id, "TO_PLANT", s.plant_id)
        edge(s.shipment_id, "FROM", s.supplier_id)
        supplies.add((s.supplier_id, s.part_id))
    for sup, part in sorted(supplies):
        edge(sup, "SUPPLIES", part)
    for model, parts in world.bom.items():
        for part in sorted(parts):
            edge(model, "USES_PART", part)
    for plant, models in world.plant_models.items():
        for model in sorted(models):
            edge(plant, "BUILDS_MODEL", model)

    for po in world.production_orders.values():
        node(
            po.id,
            "ProductionOrder",
            f"{po.id} · {po.model} · {po.plant_id} · {po.build_date:%m-%d}",
            plant_id=po.plant_id,
            build_date=po.build_date.isoformat(),
            model=po.model,
            units=po.units,
        )
        edge(po.id, "AT_PLANT", po.plant_id)
        edge(po.id, "OF_MODEL", po.model)
        edge(po.id, "ON_DAY", po.build_date.isoformat())
    for co in world.customer_orders.values():
        node(
            co.id,
            "CustomerOrder",
            f"{co.id} · promised {co.promised_date:%m-%d}",
            promised_date=co.promised_date.isoformat(),
        )
        edge(co.id, "FULFILLED_BY", co.production_order_id)
        edge(co.id, "SOLD_BY", co.dealer_id)
        edge(co.id, "FOR", co.customer_id)
    for lot in world.lots.values():
        node(
            lot.lot_id,
            "Lot",
            f"{lot.lot_id} · {lot.part_id} @ {lot.plant_id} · "
            f"{lot.first_build_date:%m-%d}..{lot.last_build_date:%m-%d}",
            first_build_date=lot.first_build_date.isoformat(),
            last_build_date=lot.last_build_date.isoformat(),
            plant_id=lot.plant_id,
            part_id=lot.part_id,
        )
        edge(lot.lot_id, "OF_PART", lot.part_id)
        edge(lot.lot_id, "AT_PLANT", lot.plant_id)
        edge(lot.lot_id, "FROM", lot.supplier_id)
    for v in world.vehicles.values():
        node(
            v.vin,
            "Vehicle",
            f"{v.vin} · {v.model} · {v.status}",
            status=v.status,
            build_date=v.build_date.isoformat(),
        )
        edge(v.vin, "BUILT_BY", v.production_order_id)
        edge(v.vin, "AT_DEALER", v.dealer_id)
        if v.customer_id:
            edge(v.vin, "OWNED_BY", v.customer_id)
    return g


def to_graphml(g: nx.MultiDiGraph, path: Path) -> None:
    """Write GraphML (all attributes are already strings/ints)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(g, path)


def ontology_mermaid() -> str:
    lines = ["flowchart LR"]
    for src, etype, dst in ONTOLOGY:
        lines.append(f"  {src} -- {etype} --> {dst}")
    return "\n".join(lines) + "\n"


def stats(g: nx.MultiDiGraph) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        out[data["type"]] = out.get(data["type"], 0) + 1
    out["_edges"] = g.number_of_edges()
    return out
