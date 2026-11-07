"""Task 1.3: impact traversals. Each returns the affected records AND the graph paths that justify them.

Handbook rules implemented here (docs/SPEC.md §5):
  rule 1  supplier delay: POs at the receiving plant whose model's BOM has the part, orig_eta <= build_date < new_eta
  rule 2  plant outage:   POs at the plant with start <= build_date <= end; restart = next working day
  rule 6  quality hold:   lot match; vehicles built at that plant in the lot's dates from models that use the part
Only POs from today on can move (past POs are already built).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import networkx as nx

from control_tower.data.loader import LAST_IDX, TODAY, CustomerOrder, Lot, ProductionOrder, Vehicle, World
from control_tower.schemas.trace import GraphEdge, GraphNode, GraphPath


def _in(g: nx.MultiDiGraph, node: str, etype: str) -> list[str]:
    return [u for u, _, k in g.in_edges(node, keys=True) if k == etype]


def _out(g: nx.MultiDiGraph, node: str, etype: str) -> list[str]:
    return [v for _, v, k in g.out_edges(node, keys=True) if k == etype]


def trace_path(g: nx.MultiDiGraph, chain: list[str]) -> GraphPath:
    """A GraphPath through `chain`; each consecutive pair is joined by the real edge, in its real direction."""
    nodes = [GraphNode(id=n, type=g.nodes[n]["type"], label=g.nodes[n]["label"]) for n in chain]
    edges: list[GraphEdge] = []
    for a, b in zip(chain, chain[1:], strict=False):
        if g.has_edge(a, b):
            etype = next(iter(g[a][b]))
            edges.append(GraphEdge(**{"from": a, "to": b, "type": etype}))
        elif g.has_edge(b, a):
            etype = next(iter(g[b][a]))
            edges.append(GraphEdge(**{"from": b, "to": a, "type": etype}))
        else:
            raise ValueError(f"no edge between {a} and {b}")
    return GraphPath(nodes=nodes, edges=edges)


@dataclass
class DisruptionImpact:
    """Affected production orders (movable ones only) of a supplier delay or plant outage."""

    kind: str  # supplier_delay | plant_outage
    plant_id: str
    disruption_end_idx: int  # first working-day index the plant can build again (may be LAST_IDX + 1)
    pos: list[ProductionOrder]  # sorted by (build_date, id)
    part_id: str | None = None
    shipment_id: str | None = None
    window: tuple[date, date] | None = None
    already_built: list[str] = field(default_factory=list)  # in the window but in the past: cannot move
    summary_paths: list[GraphPath] = field(default_factory=list)

    @property
    def po_ids(self) -> list[str]:
        return [p.id for p in self.pos]


def customer_orders_of(g: nx.MultiDiGraph, world: World, po_ids: list[str]) -> list[CustomerOrder]:
    out: list[CustomerOrder] = []
    for po in po_ids:
        for co_id in _in(g, po, "FULFILLED_BY"):
            out.append(world.customer_orders[co_id])
    return sorted(out, key=lambda c: c.id)


def _summary_paths(g: nx.MultiDiGraph, world: World, impact: DisruptionImpact, anchor: list[str]) -> list[GraphPath]:
    """One compact path per affected PO: anchor chain -> PO -> (grouped) customer orders -> (grouped) dealers."""
    paths: list[GraphPath] = []
    for po in impact.pos:
        cos = customer_orders_of(g, world, [po.id])
        dealers = sorted({c.dealer_id for c in cos})
        chain = [*anchor, po.id]
        base = trace_path(g, chain) if len(chain) > 1 else GraphPath(nodes=[], edges=[])
        nodes = list(base.nodes)
        edges = list(base.edges)
        if not nodes:
            nodes.append(GraphNode(id=po.id, type="ProductionOrder", label=g.nodes[po.id]["label"]))
        gco, gdl = f"grp:cos:{po.id}", f"grp:dealers:{po.id}"
        nodes += [
            GraphNode(
                id=gco,
                type="CustomerOrder",
                label=f"{len(cos)} customer orders",
                group="customer_orders",
                count=len(cos),
            ),
            GraphNode(id=gdl, type="Dealer", label=f"{len(dealers)} dealers", group="dealers", count=len(dealers)),
        ]
        edges += [
            GraphEdge(**{"from": gco, "to": po.id, "type": "FULFILLED_BY"}),
            GraphEdge(**{"from": gco, "to": gdl, "type": "SOLD_BY"}),
        ]
        paths.append(GraphPath(nodes=nodes, edges=edges))
    return paths


def impact_supplier_delay(
    g: nx.MultiDiGraph,
    world: World,
    *,
    plant_id: str,
    part_id: str,
    orig_eta: date,
    new_eta: date,
    shipment_id: str | None = None,
) -> DisruptionImpact:
    if shipment_id is None:  # find it through the graph: Shipment -OF_PART-> Part and -TO_PLANT-> Plant
        for s in _in(g, part_id, "OF_PART"):
            if plant_id in _out(g, s, "TO_PLANT") and g.nodes[s]["eta_date"] == orig_eta.isoformat():
                shipment_id = s
                break
    models = _in(g, part_id, "USES_PART")  # Model -USES_PART-> Part
    pos: list[ProductionOrder] = []
    built: list[str] = []
    for m in models:
        for po_id in _in(g, m, "OF_MODEL"):
            attrs = g.nodes[po_id]
            if attrs["plant_id"] != plant_id:
                continue
            bd = date.fromisoformat(attrs["build_date"])
            if not (orig_eta <= bd < new_eta):
                continue
            if bd >= TODAY:
                pos.append(world.production_orders[po_id])
            else:
                built.append(po_id)
    pos.sort(key=lambda p: (p.build_date, p.id))
    resume = world.calendar.on_or_after(new_eta)  # a weekend ETA means builds resume the next working day
    end_idx = world.calendar.idx(resume) if resume else LAST_IDX + 1
    impact = DisruptionImpact(
        kind="supplier_delay",
        plant_id=plant_id,
        disruption_end_idx=end_idx,
        pos=pos,
        part_id=part_id,
        shipment_id=shipment_id,
        window=(orig_eta, new_eta),
        already_built=sorted(built),
    )
    # Shipment -> Part -> Model -> PO -> (COs) -> (Dealers); the model hop is added per PO by trace_path.
    for po in pos:
        anchor = ([shipment_id] if shipment_id else []) + [part_id, po.model]
        impact.summary_paths.extend(_summary_paths(g, world, replace(impact, pos=[po]), anchor))
    return impact


def impact_outage(
    g: nx.MultiDiGraph,
    world: World,
    *,
    plant_id: str,
    start: date,
    end: date,
) -> DisruptionImpact:
    pos: list[ProductionOrder] = []
    built: list[str] = []
    for po_id in _in(g, plant_id, "AT_PLANT"):
        attrs = g.nodes[po_id]
        if "build_date" not in attrs:  # Shipment/Lot also point at plants but via other edge types
            continue
        bd = date.fromisoformat(attrs["build_date"])
        if start <= bd <= end:
            if bd >= TODAY:
                pos.append(world.production_orders[po_id])
            else:
                built.append(po_id)
    pos.sort(key=lambda p: (p.build_date, p.id))
    restart = world.calendar.next_working_day(end)
    end_idx = world.calendar.idx(restart) if restart else LAST_IDX + 1
    impact = DisruptionImpact(
        kind="plant_outage",
        plant_id=plant_id,
        disruption_end_idx=end_idx,
        pos=pos,
        window=(start, end),
        already_built=sorted(built),
    )
    for po in pos:
        impact.summary_paths.extend(_summary_paths(g, world, replace(impact, pos=[po]), [plant_id]))
    return impact


@dataclass
class QualityImpact:
    lot: Lot
    window: tuple[date, date]
    pos: list[ProductionOrder]
    vehicles: list[Vehicle]
    in_stock_by_dealer: dict[str, list[str]]  # dealer_id -> VINs
    owners: dict[str, list[str]]  # customer_id -> VINs of sold affected vehicles
    summary_paths: list[GraphPath] = field(default_factory=list)


def find_lots(
    world: World, *, part_id: str, plant_id: str, first: date | None = None, last: date | None = None
) -> list[Lot]:
    """Lots of the part at the plant. With a window: exact match first, otherwise every overlapping lot."""
    lots = [lt for lt in world.lots.values() if lt.part_id == part_id and lt.plant_id == plant_id]
    if first is None or last is None:
        return sorted(lots, key=lambda x: x.first_build_date)
    exact = [lt for lt in lots if lt.first_build_date == first and lt.last_build_date == last]
    if exact:
        return exact
    return sorted(
        (lt for lt in lots if lt.first_build_date <= last and lt.last_build_date >= first),
        key=lambda x: x.first_build_date,
    )


def impact_lot(g: nx.MultiDiGraph, world: World, lot_id: str) -> QualityImpact:
    lot = world.lots[lot_id]
    models = _in(g, lot.part_id, "USES_PART")
    pos: list[ProductionOrder] = []
    for m in models:
        for po_id in _in(g, m, "OF_MODEL"):
            attrs = g.nodes[po_id]
            bd = date.fromisoformat(attrs["build_date"])
            if attrs["plant_id"] == lot.plant_id and lot.first_build_date <= bd <= lot.last_build_date:
                pos.append(world.production_orders[po_id])
    pos.sort(key=lambda p: (p.build_date, p.id))
    vehicles: list[Vehicle] = []
    for po in pos:
        for vin in _in(g, po.id, "BUILT_BY"):
            vehicles.append(world.vehicles[vin])
    vehicles.sort(key=lambda v: v.vin)
    in_stock: dict[str, list[str]] = {}
    owners: dict[str, list[str]] = {}
    for v in vehicles:
        if v.status == "in_stock":
            in_stock.setdefault(v.dealer_id, []).append(v.vin)
        elif v.status == "sold" and v.customer_id:
            owners.setdefault(v.customer_id, []).append(v.vin)
    impact = QualityImpact(
        lot=lot,
        window=(lot.first_build_date, lot.last_build_date),
        pos=pos,
        vehicles=vehicles,
        in_stock_by_dealer=dict(sorted(in_stock.items())),
        owners=dict(sorted(owners.items())),
    )
    for po in pos:  # Lot -> Part -> Model -> PO -> (grouped vehicles) -> (grouped dealers/owners)
        vs = world.vehicles_by_po.get(po.id, [])
        base = trace_path(g, [lot.lot_id, lot.part_id, po.model, po.id])
        gv, gd = f"grp:vehicles:{po.id}", f"grp:dealers_owners:{po.id}"
        n_dealers = len({v.dealer_id for v in vs})
        n_owners = len({v.customer_id for v in vs if v.customer_id})
        base.nodes += [
            GraphNode(id=gv, type="Vehicle", label=f"{len(vs)} vehicles", group="vehicles", count=len(vs)),
            GraphNode(
                id=gd,
                type="Dealer",
                label=f"{n_dealers} dealers / {n_owners} owners",
                group="dealers_owners",
                count=len(vs),
            ),
        ]
        base.edges += [
            GraphEdge(**{"from": gv, "to": po.id, "type": "BUILT_BY"}),
            GraphEdge(**{"from": gv, "to": gd, "type": "AT_DEALER"}),
        ]
        impact.summary_paths.append(base)
    return impact
