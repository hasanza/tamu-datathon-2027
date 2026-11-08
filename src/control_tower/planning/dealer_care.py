"""Dealer & Customer Care planner (task 2.4, deterministic, no LLM).

Rule 4: exactly one dealer.notify per dealer with an affected customer order, listing only those orders.
Rule 5: Platinum/Gold customers get one loaner from their dealer's pool; pools are limited; priority is
Platinum before Gold, then earlier promised date, then lower customer order id. Standard customers: no loaner.
The loaner_left map is shared across the incidents of one event (compound events).
"""

from __future__ import annotations

from collections import defaultdict

from control_tower.data.loader import LOANER_TIERS, TIER_RANK, CustomerOrder, World
from control_tower.planning.policy import DEFAULT_POLICY, Policy
from control_tower.planning.supply_chain import Move
from control_tower.schemas.action import Action


def plan_care(
    world: World,
    moves: list[Move],
    loaner_left: dict[str, int],
    *,
    incident_id: str | None,
    cause: str | dict[str, str],
    policy: Policy = DEFAULT_POLICY,
    loaner_given_to: set[str] | None = None,
) -> list[Action]:
    given = loaner_given_to if loaner_given_to is not None else set()
    move_of = {m.po.id: m for m in moves}
    by_dealer: dict[str, list[CustomerOrder]] = defaultdict(list)
    for po_id in move_of:
        for co in world.cos_by_po.get(po_id, []):
            by_dealer[co.dealer_id].append(co)

    actions: list[Action] = []
    for dealer_id in sorted(by_dealer):
        cos = sorted(by_dealer[dealer_id], key=lambda c: c.id)
        lines = []
        for co in cos:
            m = move_of[co.production_order_id]
            where = f" at {m.to_plant}" if m.kind == "transfer" else ""
            why = cause[co.production_order_id] if isinstance(cause, dict) else cause
            lines.append(
                f"{co.id} (promised {co.promised_date.isoformat()}): build moves from "
                f"{m.po.build_date.isoformat()} to {m.to_date.isoformat()}{where} ({why})"
            )
        message = "Delay notice. Affected customer orders: " + "; ".join(lines) + "."
        actions.append(
            Action(
                seq=0,
                incident_id=incident_id,
                agent="dealer_care",
                tool="dealer.notify",
                args={"dealer_id": dealer_id, "customer_order_ids": [c.id for c in cos], "message": message},
                justification=f"Rule 4: one notification for {dealer_id}, only its {len(cos)} affected order(s)",
                path_ids=[cos[0].production_order_id, cos[0].id, dealer_id],
            )
        )
        entitled = sorted(
            (c for c in cos if world.customers[c.customer_id].tier in LOANER_TIERS),
            key=lambda c: (TIER_RANK[world.customers[c.customer_id].tier], c.promised_date, c.id),
        )
        for co in entitled:
            if loaner_left.get(dealer_id, 0) <= 0:
                break
            if policy.one_loaner_per_customer and co.customer_id in given:
                continue
            loaner_left[dealer_id] -= 1
            given.add(co.customer_id)
            tier = world.customers[co.customer_id].tier
            actions.append(
                Action(
                    seq=0,
                    incident_id=incident_id,
                    agent="dealer_care",
                    tool="crm.assign_loaner",
                    args={"customer_order_id": co.id},
                    justification=f"Rule 5: {tier} customer {co.customer_id}; pool {dealer_id} priority order",
                    path_ids=[co.id, co.customer_id, dealer_id],
                )
            )
    return actions
