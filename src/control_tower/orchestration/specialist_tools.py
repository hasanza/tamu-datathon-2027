"""Tools of the three specialists (docs/PLAN_V2.md §3.1). Thin wrappers over `planning/*` and `graph/traverse`:
the agent decides what to call and in what order; the numbers, dates and arguments all come out of the deterministic
planners, so the Actions are identical to what the v1 planners produce for the same inputs.

Big results are stored in `ctx.store` and returned as a handle (a string). Any tool argument that expects a list or
dict also accepts such a handle, or the ``{count, sample, stored_key}`` form the runtime shows for long lists.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from control_tower.data.loader import LAST_IDX, LOANER_TIERS, TIER_RANK
from control_tower.graph.traverse import (
    customer_orders_of as graph_customer_orders_of,
)
from control_tower.graph.traverse import (
    find_lots,
    impact_lot,
    impact_outage,
    impact_supplier_delay,
)
from control_tower.orchestration.context import EventContext, MoveSet, SpecialistResult
from control_tower.orchestration.tools import tool
from control_tower.planning.dealer_care import plan_care
from control_tower.planning.quality import plan_quality
from control_tower.planning.supply_chain import SlotBoard, moves_to_actions, plan_moves
from control_tower.schemas.action import Action

SC, DN, CCQ = "supply_chain_planner", "dealer_network", "customer_care_quality"
LIST_LIMIT = 20

Ref = list[Any] | str | dict[str, Any]  # a literal value, a handle string, or a runtime {count, sample, stored_key}


# --- helpers ----------------------------------------------------------------------------------------------------


def _ec(ctx: Any) -> EventContext:
    if not isinstance(ctx, EventContext):
        raise TypeError("specialist tools need an EventContext")
    return ctx


def stash(ctx: EventContext, label: str, value: Any) -> str:
    """Put a full value in the store and return its handle."""
    n = ctx.state["handle_n"] = ctx.state.get("handle_n", 0) + 1
    key = f"h:{ctx.event_id}:{label}:{n}"
    ctx.store[key] = value
    return key


def _is_ref(ctx: EventContext, v: Any) -> bool:
    return (isinstance(v, str) and v in ctx.store) or (isinstance(v, dict) and "stored_key" in v)


def resolve(ctx: EventContext, ref: Any) -> Any:
    """Handle string / {stored_key} dict -> the stored value; dicts are resolved value by value; anything else as is."""
    if isinstance(ref, str):
        if ref not in ctx.store:
            raise ValueError(f"unknown handle {ref!r}; pass a handle exactly as a tool returned it")
        return ctx.store[ref]
    if isinstance(ref, dict):
        if "stored_key" in ref:
            return resolve(ctx, ref["stored_key"])
        return {k: resolve(ctx, v) if _is_ref(ctx, v) else v for k, v in ref.items()}
    return ref


def _id_list(ctx: EventContext, ref: Any, what: str) -> list[str]:
    val = resolve(ctx, ref)
    if not isinstance(val, list):
        raise ValueError(f"{what} must be a list of ids or a handle to one")
    out: list[str] = []
    for x in val:
        if isinstance(x, dict):  # e.g. eligible rows
            x = x.get("co") or x.get("customer_order_id") or x.get("id") or x.get("po")
        if not isinstance(x, str):
            raise ValueError(f"{what}: unusable element {x!r}")
        out.append(x)
    return out


def _spec(ctx: EventContext, incident_id: str):
    spec = ctx.incidents.get(incident_id)
    if spec is None:
        raise ValueError(f"unknown incident_id {incident_id!r}; known: {list(ctx.incidents)}")
    return spec


def _stamp(actions: list[Action], agent: str, incident_ids: list[str]) -> list[Action]:
    ids = list(dict.fromkeys(incident_ids))
    one = ids[0] if len(ids) == 1 else None
    return [a.model_copy(update={"agent": agent, "incident_ids": ids, "incident_id": one}) for a in actions]


def _result(ctx: EventContext, agent: str, task: str, incident_id: str | None, actions: list[Action], **kw: Any):
    ids = [f"{agent}/{task}/{i}" for i in range(1, len(actions) + 1)]
    long = len(ids) > LIST_LIMIT
    res = SpecialistResult(
        task=task,
        incident_id=incident_id,
        actions_count=len(actions),
        action_ids=[] if long else ids,
        handle=stash(ctx, f"{task}-action-ids", ids) if long else None,
        findings=kw.get("findings", {}),
        paths_count=kw.get("paths_count", 0),
        reasoning_summary=kw.get("reasoning_summary", ""),
    )
    ctx.plan.set_result(agent, task, res)
    return res.model_dump(mode="json")


def _record_read(ctx: EventContext, agent: str, tool_name: str, args: dict, incident_id: str | None, path: list[str]):
    """Run a live read through the executor and keep it as an Action (it shows up in the trace as a read)."""
    if ctx.executor is None:
        raise RuntimeError("no executor configured for live reads")
    res = ctx.executor.call(ctx.event_id, tool_name, args)
    ctx.plan.reads.append(
        Action(
            seq=0,
            incident_id=incident_id,
            incident_ids=[incident_id] if incident_id else [],
            agent=agent,  # type: ignore[arg-type]
            tool=tool_name,  # type: ignore[arg-type]
            args=args,
            justification="Free read (never penalized): look at the live world before planning writes",
            path_ids=path,
            result=res,
            transport=getattr(ctx.executor, "transport", None),
        )
    )
    return res


# --- supply chain planner ----------------------------------------------------------------------------------------


def _impact(ctx: EventContext, incident_id: str):
    if incident_id in ctx.impacts:
        return ctx.impacts[incident_id]
    s = _spec(ctx, incident_id)
    if s.category == "supplier_delay":
        impact = impact_supplier_delay(
            ctx.graph,
            ctx.world,
            plant_id=s.plant_id,
            part_id=s.part_id,
            orig_eta=s.orig_eta,
            new_eta=s.new_eta,
            shipment_id=s.shipment_id,
        )
    elif s.category == "plant_outage":
        impact = impact_outage(ctx.graph, ctx.world, plant_id=s.plant_id, start=s.outage_start, end=s.outage_end)
    else:
        raise ValueError(f"{incident_id} is a {s.category}: these tools handle supplier_delay / plant_outage only")
    ctx.impacts[incident_id] = impact
    return impact


def _cause(s, impact) -> str:
    if s.category == "supplier_delay":
        return f"late shipment {impact.shipment_id} of {s.part_id}, new ETA {s.new_eta}"
    return f"{s.plant_id} outage {s.outage_start} to {s.outage_end}"


def _replay_moves(ctx: EventContext) -> None:
    """Recompute every proposed incident's moves on a fresh event board, in text order. Calling propose_slots again
    (or in a different order) therefore always yields the same, order-independent result."""
    board = ctx.slot_board
    fresh = SlotBoard(ctx.world)
    board.occ, board.loc = fresh.occ, fresh.loc
    for inc in ctx.incidents:
        if inc not in ctx.state.get("proposed", set()):
            continue
        s, impact = ctx.incidents[inc], _impact(ctx, inc)
        moves, left = plan_moves(ctx.world, board, impact, ctx.policy)
        ctx.moves[inc] = MoveSet(impact, moves, left, _cause(s, impact))
        actions = _stamp(moves_to_actions(impact, moves, inc), SC, [inc])
        ctx.plan.stage(SC, "reschedule", inc, "moves", actions)
        if (SC, "reschedule", inc) in ctx.plan.finals:  # keep a submitted result consistent with the recompute
            ctx.plan.finals[(SC, "reschedule", inc)] = actions


class AffectedBuildsArgs(BaseModel):
    incident_id: str = Field(description="A supplier_delay or plant_outage incident id, e.g. E-01#1")


@tool(
    "affected_builds",
    {SC},
    "graph",
    "Impact traversal for a supplier delay (Shipment->Part->Model->ProductionOrder at the receiving plant, ETA window) "
    "or a plant outage (Plant->ProductionOrder in the outage). Returns the affected production orders that can still "
    "move, the ones already built, the restart day and the number of graph paths.",
)
def affected_builds(ctx: EventContext, args: AffectedBuildsArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    impact = _impact(ctx, args.incident_id)
    ctx.store[f"impact:{args.incident_id}"] = impact
    restart = impact.disruption_end_idx
    return {
        "incident_id": args.incident_id,
        "kind": impact.kind,
        "plant_id": impact.plant_id,
        "shipment_id": impact.shipment_id,
        "affected_count": len(impact.pos),
        "po_ids": impact.po_ids,
        "already_built": impact.already_built,
        "restart_day": ctx.world.calendar.date_of(restart).isoformat() if restart <= LAST_IDX else None,
        "window": [d.isoformat() for d in impact.window] if impact.window else None,
        "paths_count": len(impact.summary_paths),
    }


class GetScheduleArgs(BaseModel):
    plant_id: str
    date: date
    incident_id: str | None = None


@tool(
    "get_schedule",
    {SC},
    "mcp-read",
    "LIVE read of one plant's schedule on one working day: free slots and the orders built that day. Free, never "
    "penalized. Use it to check a slot before relying on it.",
)
def get_schedule(ctx: EventContext, args: GetScheduleArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    day = args.date.isoformat()
    res = _record_read(
        ctx, SC, "mes.get_schedule", {"plant_id": args.plant_id, "date": day}, args.incident_id, [args.plant_id]
    )
    if not res.ok:
        return {"ok": False, "error": res.error}
    r = res.response or {}
    return {
        "ok": True,
        "plant_id": args.plant_id,
        "date": day,
        "free_slots": r.get("free_slots"),
        "orders": [o.get("production_order_id") for o in r.get("orders", [])],
    }


class ProposeSlotsArgs(BaseModel):
    incident_id: str


@tool(
    "propose_slots",
    {SC},
    "code",
    "Handbook rule 3 planner: for every affected production order of the incident choose the earliest feasible slot "
    "(same plant at/after the restart day, else transfer to another plant that builds the model). Slots are shared by "
    "all incidents of the event. Idempotent: calling again recomputes and replaces this incident's moves.",
)
def propose_slots(ctx: EventContext, args: ProposeSlotsArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    _impact(ctx, args.incident_id)
    ctx.state.setdefault("proposed", set()).add(args.incident_id)
    _replay_moves(ctx)
    ms = ctx.moves[args.incident_id]
    return {
        "incident_id": args.incident_id,
        "moves": [
            {
                "po": m.po.id,
                "kind": m.kind,
                "from": f"{m.po.plant_id} {m.po.build_date.isoformat()}",
                "to_plant": m.to_plant,
                "to_date": m.to_date.isoformat(),
                "reason": m.reason,
            }
            for m in ms.moves
        ],
        "reschedules": sum(m.kind == "reschedule" for m in ms.moves),
        "transfers": sum(m.kind == "transfer" for m in ms.moves),
        "unplaceable": [p.id for p in ms.unplaceable],
    }


class SubmitMovesArgs(BaseModel):
    incident_id: str
    reasoning_summary: str = Field(
        default="", description="2-3 sentences: what was affected and how it was rescheduled"
    )


@tool(
    "submit_reschedule_plan",
    {SC},
    "control",
    "FINAL step. Submit the incident's rescheduling plan built by propose_slots (a second submit replaces the first). "
    "Returns the SpecialistResult to copy into `final`.",
)
def sc_submit_plan(ctx: EventContext, args: SubmitMovesArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    ms = ctx.moves.get(args.incident_id)
    if ms is None:
        raise ValueError("call propose_slots for this incident first")
    actions = ctx.plan.staged_actions(SC, "reschedule", args.incident_id)
    return _result(
        ctx,
        SC,
        "reschedule",
        args.incident_id,
        actions,
        findings={
            "reschedules": sum(m.kind == "reschedule" for m in ms.moves),
            "transfers": sum(m.kind == "transfer" for m in ms.moves),
            "unplaceable": [p.id for p in ms.unplaceable],
            "already_built": len(ms.impact.already_built),
        },
        paths_count=len(ms.impact.summary_paths),
        reasoning_summary=args.reasoning_summary,
    )


# --- dealer network ---------------------------------------------------------------------------------------------


class CustomerOrdersArgs(BaseModel):
    po_ids: Ref = Field(description="Moved production order ids, or a handle to such a list")


@tool(
    "customer_orders_of",
    {DN},
    "graph",
    "Graph hop ProductionOrder<-FULFILLED_BY-CustomerOrder-SOLD_BY->Dealer / -FOR->Customer for the given production "
    "orders. Returns affected customer orders by dealer (as a handle plus per-dealer counts) and customer tiers.",
)
def customer_orders_of(ctx: EventContext, args: CustomerOrdersArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    po_ids = _id_list(ctx, args.po_ids, "po_ids")
    unknown = [p for p in po_ids if p not in ctx.world.production_orders]
    if unknown:
        raise ValueError(f"unknown production orders {unknown[:5]}")
    cos = graph_customer_orders_of(ctx.graph, ctx.world, po_ids)
    by_dealer: dict[str, list[str]] = defaultdict(list)
    tiers: dict[str, int] = defaultdict(int)
    for c in cos:
        by_dealer[c.dealer_id].append(c.id)
        tiers[ctx.world.customers[c.customer_id].tier] += 1
    by_dealer = dict(sorted(by_dealer.items()))
    return {
        "po_count": len(po_ids),
        "co_count": len(cos),
        "dealer_count": len(by_dealer),
        "by_dealer": stash(ctx, "by_dealer", by_dealer),
        "by_dealer_counts": {d: len(v) for d, v in by_dealer.items()},
        "co_ids": stash(ctx, "co_ids", [c.id for c in cos]),
        "customer_tiers": dict(tiers),
        "customers": len({c.customer_id for c in cos}),
    }


class ComposeNoticesArgs(BaseModel):
    by_dealer: Ref = Field(description="{dealer_id: [customer order ids]} or the handle customer_orders_of returned")


@tool(
    "compose_notices",
    {DN},
    "code",
    "Handbook rule 4: compose exactly ONE dealer.notify per dealer listing exactly that dealer's affected customer "
    "orders. Every order must be a customer order of a moved production order, listed under its own dealer.",
)
def compose_notices(ctx: EventContext, args: ComposeNoticesArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    by_dealer = resolve(ctx, args.by_dealer)
    if not isinstance(by_dealer, dict):
        raise ValueError("by_dealer must be {dealer_id: [co ids]} or a handle to it")
    moved = {m.po.id for ms in ctx.moves.values() for m in ms.moves}
    if not moved:
        raise ValueError("no moves proposed yet (the supply chain planner must run first)")
    co_set: set[str] = set()
    for dealer_id, cos in by_dealer.items():
        for co_id in _id_list(ctx, cos, f"by_dealer[{dealer_id}]"):
            co = ctx.world.customer_orders.get(co_id)
            if co is None:
                raise ValueError(f"unknown customer order {co_id}")
            if co.dealer_id != dealer_id:
                raise ValueError(f"{co_id} belongs to dealer {co.dealer_id}, not {dealer_id}")
            if co.production_order_id not in moved:
                raise ValueError(f"{co_id} is not a customer order of a moved production order (rule 10)")
            co_set.add(co_id)
    all_moves = [m for ms in ctx.moves.values() for m in ms.moves]
    cause = {m.po.id: ms.cause for ms in ctx.moves.values() for m in ms.moves}
    acts = plan_care(
        ctx.world, all_moves, {}, incident_id=None, cause=cause, policy=ctx.policy, co_ids=co_set, include_loaners=False
    )
    po_inc = {m.po.id: inc for inc, ms in ctx.moves.items() for m in ms.moves}
    out: list[Action] = []
    for a in acts:
        incs = [po_inc[ctx.world.customer_orders[c].production_order_id] for c in a.args["customer_order_ids"]]
        out.extend(_stamp([a], DN, incs))
    ctx.plan.stage(DN, "dealer_comms", None, "notices", out)
    return {
        "notices": len(out),
        "dealers": [a.args["dealer_id"] for a in out],
        "orders_listed": sum(len(a.args["customer_order_ids"]) for a in out),
    }


class ComposeStopSalesArgs(BaseModel):
    incident_id: str = Field(description="The quality_hold incident")
    vins_by_dealer: Ref = Field(
        description="{dealer_id: [VINs]} or the in_stock_by_dealer handle from affected_vehicles"
    )


@tool(
    "compose_stop_sales",
    {DN},
    "code",
    "Handbook rule 6: compose dealer.stop_sale, one per dealer, for the unsold (in_stock) affected vehicles listed. "
    "Every VIN must be an unsold vehicle of the affected lot at that dealer.",
)
def compose_stop_sales(ctx: EventContext, args: ComposeStopSalesArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    q = ctx.impacts.get(args.incident_id)
    if q is None or not hasattr(q, "in_stock_by_dealer"):
        raise ValueError("the lot's vehicles are not known yet: affected_vehicles must run for this incident first")
    raw = resolve(ctx, args.vins_by_dealer)
    if not isinstance(raw, dict):
        raise ValueError("vins_by_dealer must be {dealer_id: [VINs]} or a handle to it")
    subset: dict[str, list[str]] = {}
    for dealer_id, vins in raw.items():
        vins = _id_list(ctx, vins, f"vins_by_dealer[{dealer_id}]")
        bad = sorted(set(vins) - set(q.in_stock_by_dealer.get(dealer_id, [])))
        if bad:
            raise ValueError(f"{bad[:3]} are not unsold affected vehicles of {q.lot.lot_id} at {dealer_id} (rule 10)")
        if vins:
            subset[dealer_id] = sorted(vins)
    s = _spec(ctx, args.incident_id)
    acts = plan_quality(
        ctx.world,
        replace(q, in_stock_by_dealer=subset, owners={}),
        incident_id=args.incident_id,
        reason=f"{s.supplier_id} reported a defect in {s.part_id}",
    )
    out = _stamp([a for a in acts if a.tool == "dealer.stop_sale"], DN, [args.incident_id])
    ctx.plan.stage(DN, "dealer_comms", None, f"stop_sales:{args.incident_id}", out)
    return {"stop_sales": len(out), "dealers": sorted(subset), "vins": sum(len(v) for v in subset.values())}


class SubmitDealerArgs(BaseModel):
    reasoning_summary: str = ""


@tool(
    "submit_dealer_plan",
    {DN},
    "control",
    "FINAL step. Submit everything composed so far (notices and stop-sales) as the event's dealer communications "
    "(a second submit replaces the first). Returns the SpecialistResult to copy into `final`.",
)
def dn_submit_plan(ctx: EventContext, args: SubmitDealerArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    actions = ctx.plan.staged_actions(DN, "dealer_comms")
    if not actions:
        raise ValueError("nothing composed yet: call compose_notices and/or compose_stop_sales first")
    return _result(
        ctx,
        DN,
        "dealer_comms",
        None,
        actions,
        findings={
            "notices": sum(a.tool == "dealer.notify" for a in actions),
            "stop_sales": sum(a.tool == "dealer.stop_sale" for a in actions),
        },
        paths_count=sum(len(getattr(ms.impact, "summary_paths", [])) for ms in ctx.moves.values()),
        reasoning_summary=args.reasoning_summary,
    )


# --- customer care & quality ------------------------------------------------------------------------------------


def _quality_incident(ctx: EventContext, incident_id: str | None, lot_id: str | None = None) -> str:
    if incident_id:
        s = _spec(ctx, incident_id)
        if s.category != "quality_hold":
            raise ValueError(f"{incident_id} is a {s.category}, not a quality_hold")
        return incident_id
    cands = [i for i, s in ctx.incidents.items() if s.category == "quality_hold" and s.lot_id in (None, lot_id)]
    if len(cands) != 1:
        raise ValueError(f"cannot tell which quality incident this is (candidates {cands}); pass incident_id")
    return cands[0]


def _lot_impact(ctx: EventContext, incident_id: str):
    q = ctx.impacts.get(incident_id)
    if q is None or not hasattr(q, "in_stock_by_dealer"):
        raise ValueError("call affected_vehicles(lot_id) for this incident first")
    return q


def _quality_reason(ctx: EventContext, incident_id: str) -> str:
    s = _spec(ctx, incident_id)
    return f"{s.supplier_id} reported a defect in {s.part_id}"


class MatchLotArgs(BaseModel):
    incident_id: str


@tool(
    "match_lot",
    {CCQ},
    "graph",
    "Find the part lot a quality incident is about: the resolved lot id if there is one, otherwise the lots of that "
    "part at that plant whose build window matches (candidates, if more than one fits).",
)
def match_lot(ctx: EventContext, args: MatchLotArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    s = _spec(ctx, args.incident_id)
    if s.category != "quality_hold":
        raise ValueError(f"{args.incident_id} is a {s.category}, not a quality_hold")

    def row(lt):
        return {
            "lot_id": lt.lot_id,
            "part_id": lt.part_id,
            "plant_id": lt.plant_id,
            "first_build_date": lt.first_build_date.isoformat(),
            "last_build_date": lt.last_build_date.isoformat(),
            "supplier_id": lt.supplier_id,
        }

    if s.lot_id and s.lot_id in ctx.world.lots:
        return {"matched": True, "lot": row(ctx.world.lots[s.lot_id]), "candidates": [], "source": "resolved lot id"}
    if not (s.part_id and s.plant_id):
        return {"matched": False, "lot": None, "candidates": [], "note": "incident has no part and plant to match on"}
    lots = find_lots(
        ctx.world, part_id=s.part_id, plant_id=s.plant_id, first=s.build_window_start, last=s.build_window_end
    )
    if len(lots) == 1:
        return {"matched": True, "lot": row(lots[0]), "candidates": [], "source": "part+plant+window"}
    return {"matched": False, "lot": None, "candidates": [row(lt) for lt in lots], "source": "part+plant+window"}


class AffectedVehiclesArgs(BaseModel):
    lot_id: str
    incident_id: str | None = Field(
        default=None, description="Optional; inferred when the event has one quality incident"
    )


@tool(
    "affected_vehicles",
    {CCQ},
    "graph",
    "Handbook rule 6 traversal: Lot->Part->Model->ProductionOrder (same plant, lot build dates)->Vehicle->Dealer/Owner. "
    "Returns unsold vehicles by dealer and sold vehicles by owner (both as handles, with counts) and the path count.",
)
def affected_vehicles(ctx: EventContext, args: AffectedVehiclesArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    if args.lot_id not in ctx.world.lots:
        raise ValueError(f"unknown lot {args.lot_id}")
    inc = _quality_incident(ctx, args.incident_id, args.lot_id)
    q = impact_lot(ctx.graph, ctx.world, args.lot_id)
    ctx.impacts[inc] = q
    return {
        "incident_id": inc,
        "lot_id": args.lot_id,
        "production_orders": len(q.pos),
        "vehicles": len(q.vehicles),
        "in_stock_by_dealer": stash(ctx, "in_stock_by_dealer", q.in_stock_by_dealer),
        "in_stock_counts": {d: len(v) for d, v in q.in_stock_by_dealer.items()},
        "in_stock_total": sum(len(v) for v in q.in_stock_by_dealer.values()),
        "owners": stash(ctx, "owners", q.owners),
        "owner_count": len(q.owners),
        "sold_total": sum(len(v) for v in q.owners.values()),
        "paths_count": len(q.summary_paths),
    }


class EligibleArgs(BaseModel):
    co_ids: Ref = Field(description="Affected customer order ids, or a handle to such a list")


@tool(
    "eligible_customers",
    {CCQ},
    "graph",
    "Handbook rule 5 filter: of the given affected customer orders keep those whose customer is Platinum or Gold "
    "(Standard customers get no loaner). Returns tier, promised date and dealer per order, as a handle plus counts.",
)
def eligible_customers(ctx: EventContext, args: EligibleArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    co_ids = _id_list(ctx, args.co_ids, "co_ids")
    rows, standard = [], 0
    for cid in co_ids:
        co = ctx.world.customer_orders.get(cid)
        if co is None:
            raise ValueError(f"unknown customer order {cid}")
        tier = ctx.world.customers[co.customer_id].tier
        if tier in LOANER_TIERS:
            rows.append(
                {
                    "co": co.id,
                    "customer_id": co.customer_id,
                    "tier": tier,
                    "promised_date": co.promised_date.isoformat(),
                    "dealer_id": co.dealer_id,
                }
            )
        else:
            standard += 1
    rows.sort(key=lambda r: (r["dealer_id"], TIER_RANK[r["tier"]], r["promised_date"], r["co"]))
    per_dealer: dict[str, int] = defaultdict(int)
    for r in rows:
        per_dealer[r["dealer_id"]] += 1
    return {
        "eligible": stash(ctx, "eligible", rows),
        "eligible_count": len(rows),
        "dealer_ids": sorted(per_dealer),
        "standard_count": standard,
        "eligible_by_dealer": dict(sorted(per_dealer.items())),
        "preview": rows[:5],
    }


class LoanerAvailabilityArgs(BaseModel):
    dealer_ids: Ref | None = Field(
        default=None, description="Dealer ids (list or handle): ONE call reads all of them. Preferred."
    )
    dealer_id: str | None = Field(default=None, description="A single dealer (kept for compatibility)")


@tool(
    "loaner_availability",
    {CCQ},
    "mcp-read",
    "LIVE read of how many loaner cars each dealer still has free (free, never penalized). Give ALL dealers at once in "
    "dealer_ids (eligible_customers returns them); one live read is made per dealer. Returns {pools, handle}; "
    "rank_and_assign uses the latest pools automatically.",
)
def loaner_availability(ctx: EventContext, args: LoanerAvailabilityArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    ids = _id_list(ctx, args.dealer_ids, "dealer_ids") if args.dealer_ids is not None else []
    if args.dealer_id:
        ids.append(args.dealer_id)
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError("pass dealer_ids (or dealer_id)")
    pools: dict[str, int] = {}
    errors: dict[str, str | None] = {}
    for d in ids:
        res = _record_read(ctx, CCQ, "crm.loaner_availability", {"dealer_id": d}, None, [d])
        if res.ok:
            pools[d] = (res.response or {}).get("available")
        else:
            errors[d] = res.error
    ctx.state.setdefault("pools", {}).update(pools)
    out: dict[str, Any] = {"ok": not errors, "pools": pools, "handle": stash(ctx, "pools", dict(pools))}
    if errors:
        out["errors"] = errors
    return out


class RankAssignArgs(BaseModel):
    eligible: Ref = Field(description="Rows/ids of eligible customer orders, or the `eligible` handle")
    pools: dict[str, Any] | str | None = Field(
        default=None,
        description="{dealer_id: free loaners} or the pools handle from loaner_availability; omitted = the latest "
        "pools read, else the table pools",
    )


@tool(
    "rank_and_assign",
    {CCQ},
    "code",
    "Handbook rule 5: within each dealer's pool rank Platinum before Gold, then earlier promised date, then lower "
    "customer order id, and compose one crm.assign_loaner per customer order while the pool lasts. Empty pool = no "
    "assignment.",
)
def rank_and_assign(ctx: EventContext, args: RankAssignArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    ids = set(_id_list(ctx, args.eligible, "eligible"))
    unknown = sorted(c for c in ids if c not in ctx.world.customer_orders)
    if unknown:
        raise ValueError(f"unknown customer orders {unknown[:5]}")
    all_moves = [m for ms in ctx.moves.values() for m in ms.moves]
    if not all_moves:
        raise ValueError("no moves proposed yet (the supply chain planner must run first)")
    po_inc = {m.po.id: inc for inc, ms in ctx.moves.items() for m in ms.moves}
    ignored = sorted(c for c in ids if ctx.world.customer_orders[c].production_order_id not in po_inc)
    given_pools = resolve(ctx, args.pools) if args.pools is not None else ctx.state.get("pools", {})
    if isinstance(given_pools, dict) and "pools" in given_pools:
        given_pools = given_pools["pools"]
    pool = {**ctx.world.loaner_pool, **{k: int(v) for k, v in given_pools.items()}}
    acts = plan_care(
        ctx.world,
        all_moves,
        dict(pool),
        incident_id=None,
        cause="",
        policy=ctx.policy,
        loaner_given_to=set(),
        co_ids=ids,
        include_notices=False,
    )
    out: list[Action] = []
    for a in acts:
        po = ctx.world.customer_orders[a.args["customer_order_id"]].production_order_id
        out.extend(_stamp([a], CCQ, [po_inc[po]]))
    ctx.plan.stage(CCQ, "loaners", None, "loaners", out)
    assigned: dict[str, list[str]] = defaultdict(list)
    for a in out:
        assigned[ctx.world.customer_orders[a.args["customer_order_id"]].dealer_id].append(a.args["customer_order_id"])
    waiting: dict[str, list[str]] = defaultdict(list)
    for c in sorted(ids):
        co = ctx.world.customer_orders[c]
        if c not in ignored and ctx.world.customers[co.customer_id].tier in LOANER_TIERS:
            if c not in assigned.get(co.dealer_id, []):
                waiting[co.dealer_id].append(c)
    return {
        "assignments": len(out),
        "by_dealer": {d: {"pool": pool[d], "assigned": v} for d, v in sorted(assigned.items())},
        "unserved_for_lack_of_pool": dict(sorted(waiting.items())),
        "ignored_not_affected": ignored,
    }


class ComposeHoldArgs(BaseModel):
    lot_id: str
    incident_id: str | None = None


@tool("compose_hold", {CCQ}, "code", "Handbook rule 6: compose quality.hold_lot for the lot.")
def compose_hold(ctx: EventContext, args: ComposeHoldArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    if args.lot_id not in ctx.world.lots:
        raise ValueError(f"unknown lot {args.lot_id}")
    inc = _quality_incident(ctx, args.incident_id, args.lot_id)
    q = ctx.impacts.get(inc)
    if q is None or not hasattr(q, "in_stock_by_dealer") or q.lot.lot_id != args.lot_id:
        q = impact_lot(ctx.graph, ctx.world, args.lot_id)
        ctx.impacts[inc] = q
    acts = plan_quality(
        ctx.world, replace(q, in_stock_by_dealer={}, owners={}), incident_id=inc, reason=_quality_reason(ctx, inc)
    )
    out = _stamp([a for a in acts if a.tool == "quality.hold_lot"], CCQ, [inc])
    ctx.plan.stage(CCQ, "quality_hold", inc, "hold", out)
    return {"holds": len(out), "lot_id": args.lot_id, "incident_id": inc}


class OwnerContactsArgs(BaseModel):
    incident_id: str
    owners: Ref = Field(description="{customer_id: [VINs]} or the `owners` handle from affected_vehicles")


@tool(
    "compose_owner_contacts",
    {CCQ},
    "code",
    "Handbook rule 6: compose crm.notify_customer, once per owner of a sold affected vehicle.",
)
def compose_owner_contacts(ctx: EventContext, args: OwnerContactsArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    inc = _quality_incident(ctx, args.incident_id)
    q = _lot_impact(ctx, inc)
    raw = resolve(ctx, args.owners)
    if not isinstance(raw, dict):
        raise ValueError("owners must be {customer_id: [VINs]} or a handle to it")
    subset: dict[str, list[str]] = {}
    for cust, vins in raw.items():
        vins = _id_list(ctx, vins, f"owners[{cust}]")
        bad = sorted(set(vins) - set(q.owners.get(cust, [])))
        if bad:
            raise ValueError(f"{cust} does not own sold affected vehicle(s) {bad[:3]} of {q.lot.lot_id} (rule 10)")
        if vins:
            subset[cust] = sorted(vins)
    acts = plan_quality(
        ctx.world, replace(q, in_stock_by_dealer={}, owners=subset), incident_id=inc, reason=_quality_reason(ctx, inc)
    )
    out = _stamp([a for a in acts if a.tool == "crm.notify_customer"], CCQ, [inc])
    ctx.plan.stage(CCQ, "quality_hold", inc, "owner_contacts", out)
    return {"owner_contacts": len(out), "owners": len(subset)}


class SubmitCareArgs(BaseModel):
    task: str = Field(description="'quality_hold' (hold + owner contacts, per incident) or 'loaners' (event-wide)")
    incident_id: str | None = Field(default=None, description="Required for quality_hold")
    reasoning_summary: str = ""


@tool(
    "submit_care_plan",
    {CCQ},
    "control",
    "FINAL step. Submit the staged actions of the task: quality_hold (needs incident_id) or loaners. A second submit "
    "for the same task replaces the first. Returns the SpecialistResult to copy into `final`.",
)
def ccq_submit_plan(ctx: EventContext, args: SubmitCareArgs) -> dict[str, Any]:
    ctx = _ec(ctx)
    if args.task == "quality_hold":
        inc = _quality_incident(ctx, args.incident_id)
        actions = ctx.plan.staged_actions(CCQ, "quality_hold", inc)
        if not any(a.tool == "quality.hold_lot" for a in actions):
            raise ValueError("compose_hold first")
        q = ctx.impacts.get(inc)
        return _result(
            ctx,
            CCQ,
            "quality_hold",
            inc,
            actions,
            findings={
                "lot_id": q.lot.lot_id,
                "holds": sum(a.tool == "quality.hold_lot" for a in actions),
                "owner_contacts": sum(a.tool == "crm.notify_customer" for a in actions),
                "unsold_to_stop": sum(len(v) for v in q.in_stock_by_dealer.values()),
            },
            paths_count=len(q.summary_paths),
            reasoning_summary=args.reasoning_summary,
        )
    if args.task == "loaners":
        actions = ctx.plan.staged_actions(CCQ, "loaners")
        return _result(
            ctx,
            CCQ,
            "loaners",
            None,
            actions,
            findings={"assignments": len(actions)},
            reasoning_summary=args.reasoning_summary,
        )
    raise ValueError("task must be 'quality_hold' or 'loaners'")
