"""Quality planner (task 2.5, deterministic, no LLM). Rule 6: hold the lot, stop sale of unsold affected vehicles
at their dealers, notify the owner of every sold affected vehicle (once per owner)."""

from __future__ import annotations

from control_tower.data.loader import World
from control_tower.graph.traverse import QualityImpact
from control_tower.schemas.action import Action


def plan_quality(world: World, impact: QualityImpact, *, incident_id: str | None, reason: str) -> list[Action]:
    lot = impact.lot
    actions = [
        Action(
            seq=0,
            incident_id=incident_id,
            agent="quality",
            tool="quality.hold_lot",
            args={"lot_id": lot.lot_id},
            justification=(
                f"Rule 6: {lot.lot_id} ({lot.part_id} at {lot.plant_id}, "
                f"built {lot.first_build_date}..{lot.last_build_date})"
            ),
            path_ids=[lot.lot_id],
        )
    ]
    for dealer_id, vins in impact.in_stock_by_dealer.items():
        actions.append(
            Action(
                seq=0,
                incident_id=incident_id,
                agent="quality",
                tool="dealer.stop_sale",
                args={"dealer_id": dealer_id, "vins": sorted(vins)},
                justification=f"Rule 6: {len(vins)} unsold vehicle(s) from {lot.lot_id} at {dealer_id}",
                path_ids=[lot.lot_id, vins[0], dealer_id],
            )
        )
    for customer_id, vins in impact.owners.items():
        name = world.customers[customer_id].name
        actions.append(
            Action(
                seq=0,
                incident_id=incident_id,
                agent="quality",
                tool="crm.notify_customer",
                args={
                    "customer_id": customer_id,
                    "message": (
                        f"Dear {name}: a quality issue ({reason}) affects part lot {lot.lot_id} installed in your "
                        f"vehicle ({', '.join(sorted(vins))}). Please contact your dealer to schedule an inspection."
                    ),
                },
                justification=f"Rule 6: owner of sold vehicle(s) {', '.join(sorted(vins))} from {lot.lot_id}",
                path_ids=[lot.lot_id, vins[0], customer_id],
            )
        )
    return actions
