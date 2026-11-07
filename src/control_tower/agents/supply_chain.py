"""Supply Chain Planner (task 2.3, deterministic, no LLM): earliest feasible slot, reschedule or transfer.

Rule 3: move each affected PO to the earliest feasible slot. Same plant: day >= disruption end with a free slot
(5 slots/day). If none, transfer to another plant that builds the model on a day with a free slot. Never move
unaffected orders. The SlotBoard is shared by every incident of one event so slots are counted consistently.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

from control_tower.agents.policy import DEFAULT_POLICY, Policy
from control_tower.data.loader import LAST_IDX, ProductionOrder, World
from control_tower.graph.traverse import DisruptionImpact
from control_tower.schemas.action import Action


class SlotBoard:
    """Live occupancy of (plant, day-index) slots for one event's world."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.cap = {pid: p.slots_per_day for pid, p in world.plants.items()}
        self.occ: dict[tuple[str, int], set[str]] = defaultdict(set)
        self.loc: dict[str, tuple[str, int]] = {}
        for po in world.production_orders.values():
            idx = world.calendar.idx(po.build_date)
            if idx >= 0:
                self.occ[(po.plant_id, idx)].add(po.id)
                self.loc[po.id] = (po.plant_id, idx)

    def free(self, plant: str, idx: int) -> int:
        return self.cap[plant] - len(self.occ[(plant, idx)])

    def move(self, po_id: str, plant: str, idx: int) -> None:
        old = self.loc[po_id]
        self.occ[old].discard(po_id)
        self.occ[(plant, idx)].add(po_id)
        self.loc[po_id] = (plant, idx)


@dataclass(frozen=True)
class Move:
    po: ProductionOrder
    kind: Literal["reschedule", "transfer"]
    to_plant: str
    to_idx: int
    to_date: date
    reason: str


def plan_moves(
    world: World, board: SlotBoard, impact: DisruptionImpact, policy: Policy = DEFAULT_POLICY
) -> tuple[list[Move], list[ProductionOrder]]:
    """Returns (moves, unplaceable). Mutates `board` so later incidents of the same event see the new occupancy."""
    moves: list[Move] = []
    unplaceable: list[ProductionOrder] = []
    start = max(impact.disruption_end_idx, 0)
    for po in sorted(impact.pos, key=lambda p: (p.build_date, p.id)):
        cur_plant, cur_idx = board.loc[po.id]
        placed = False
        for idx in range(start, LAST_IDX + 1):
            if board.free(cur_plant, idx) > 0 and (cur_plant, idx) != (cur_plant, cur_idx):
                d = world.calendar.date_of(idx)
                moves.append(
                    Move(
                        po,
                        "reschedule",
                        cur_plant,
                        idx,
                        d,
                        f"earliest free {cur_plant} slot at/after restart",
                    )
                )
                board.move(po.id, cur_plant, idx)
                placed = True
                break
        if placed:
            continue
        lo = 0 if policy.transfer_min_day == "today" else start
        others = sorted(world.builders[po.model] - {cur_plant})
        for idx in range(lo, LAST_IDX + 1):
            target = next((p for p in others if board.free(p, idx) > 0), None)
            if target:
                d = world.calendar.date_of(idx)
                moves.append(
                    Move(
                        po,
                        "transfer",
                        target,
                        idx,
                        d,
                        f"no free {cur_plant} slot; earliest free {target} slot",
                    )
                )
                board.move(po.id, target, idx)
                placed = True
                break
        if not placed:
            unplaceable.append(po)
    return moves, unplaceable


def moves_to_actions(impact: DisruptionImpact, moves: list[Move], incident_id: str | None) -> list[Action]:
    why = {
        "supplier_delay": f"Rule 1+3: needs {impact.part_id} and builds before the new ETA",
        "plant_outage": "Rule 2+3: build falls inside the outage",
    }[impact.kind]
    actions: list[Action] = []
    for m in moves:
        if m.kind == "reschedule":
            tool, args = "mes.reschedule", {"production_order_id": m.po.id, "new_date": m.to_date.isoformat()}
        else:
            tool = "mes.transfer"
            args = {
                "production_order_id": m.po.id,
                "to_plant_id": m.to_plant,
                "new_date": m.to_date.isoformat(),
            }
        actions.append(
            Action(
                seq=0,
                incident_id=incident_id,
                agent="supply_chain",
                tool=tool,
                args=args,
                justification=f"{why}; {m.reason}",
                path_ids=[x for x in (impact.shipment_id, impact.part_id, m.po.model, m.po.id) if x],
            )
        )
    return actions
