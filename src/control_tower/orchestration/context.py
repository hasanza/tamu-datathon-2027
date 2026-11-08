"""EventContext: everything the specialists' tools share for ONE event (docs/PLAN_V2.md §3, §3.1).

It extends the 6.1 `ToolContext` (so the runtime and the sample tools keep working) with the resolved incidents, one
event-wide `SlotBoard` (a compound event shares slots) and the `PlanAccumulator` that collects what each specialist
submits. `set_result` REPLACES an earlier result for the same agent + task (+ incident), which is what makes a
correction round safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from control_tower.orchestration.tools import ToolContext
from control_tower.planning.policy import DEFAULT_POLICY, Policy
from control_tower.planning.supply_chain import SlotBoard
from control_tower.schemas.action import Action
from control_tower.schemas.incident import IncidentSpec

# Canonical write order (PLAN_V2 §5: moves, notices, loaners, holds, stop-sales, owner contacts).
PHASE_ORDER = (
    "mes.reschedule",
    "mes.transfer",
    "dealer.notify",
    "crm.assign_loaner",
    "quality.hold_lot",
    "dealer.stop_sale",
    "crm.notify_customer",
)


class SpecialistResult(BaseModel):
    """What a specialist hands back to the coordinator (also the agents' `final` schema)."""

    task: str = Field(description="The task this result is for, e.g. reschedule, dealer_comms, quality_hold, loaners")
    incident_id: str | None = Field(default=None, description="Set for per-incident tasks, null for event-wide ones")
    actions_count: int = 0
    action_ids: list[str] = Field(
        default_factory=list, description="'<agent>/<task>/<n>' ids; empty when handle is set"
    )
    handle: str | None = Field(default=None, description="Store key of the full action id list when it is long")
    findings: dict[str, Any] = Field(default_factory=dict)
    paths_count: int = 0
    reasoning_summary: str = ""


@dataclass
class MoveSet:
    """One incident's slot proposal: kept so dealer notices and loaners use the very same moves."""

    impact: Any  # DisruptionImpact
    moves: list[Any]  # list[Move]
    unplaceable: list[Any]
    cause: str


@dataclass
class PlanAccumulator:
    """Actions staged by tools (per bin, replaced on recompute) and finalized by `set_result`."""

    staged: dict[tuple[str, str, str | None, str], list[Action]] = field(default_factory=dict)
    results: dict[tuple[str, str, str | None], SpecialistResult] = field(default_factory=dict)
    finals: dict[tuple[str, str, str | None], list[Action]] = field(default_factory=dict)
    reads: list[Action] = field(default_factory=list)  # live reads (mes.get_schedule, crm.loaner_availability)

    def stage(self, agent: str, task: str, incident_id: str | None, bin_: str, actions: list[Action]) -> None:
        self.staged[(agent, task, incident_id, bin_)] = list(actions)

    def staged_actions(self, agent: str, task: str, incident_id: str | None = None) -> list[Action]:
        """Staged actions of a task; a per-incident query returns only that incident's bins."""
        out: list[Action] = []
        for (a, t, inc, _bin), acts in self.staged.items():
            if a == agent and t == task and (incident_id is None or inc == incident_id):
                out.extend(acts)
        return out

    def set_result(self, agent: str, task: str, result: SpecialistResult) -> None:
        """Finalize: snapshot the staged actions of (agent, task[, incident]) and REPLACE any previous result."""
        key = (agent, task, result.incident_id)
        self.results[key] = result
        self.finals[key] = self.staged_actions(agent, task, result.incident_id)

    # -- views ------------------------------------------------------------------------------------------------------
    def actions(self) -> list[Action]:
        """All finalized write actions in canonical phase order (stable within a phase)."""
        flat = [a for acts in self.finals.values() for a in acts]
        rank = {t: i for i, t in enumerate(PHASE_ORDER)}
        return sorted(flat, key=lambda a: rank.get(a.tool, len(rank)))

    def by_incident(self) -> dict[str, list[Action]]:
        out: dict[str, list[Action]] = {}
        for a in self.actions():
            for inc in a.incident_ids or ([a.incident_id] if a.incident_id else []):
                out.setdefault(inc, []).append(a)
        return out

    def by_task(self) -> dict[str, list[Action]]:
        out: dict[str, list[Action]] = {}
        for (_agent, task, _inc), acts in self.finals.items():
            out.setdefault(task, []).extend(acts)
        return out


@dataclass
class EventContext(ToolContext):
    index: Any = None  # EntityIndex
    twin: Any = None
    policy: Policy = DEFAULT_POLICY
    event: dict[str, Any] = field(default_factory=dict)
    timeline: Any = None
    incidents: dict[str, IncidentSpec] = field(default_factory=dict)  # in text order
    slot_board: SlotBoard | None = None
    plan: PlanAccumulator = field(default_factory=PlanAccumulator)
    run_mode: str = "sequential"
    moves: dict[str, MoveSet] = field(default_factory=dict)  # incident_id -> latest slot proposal
    impacts: dict[str, Any] = field(default_factory=dict)  # incident_id -> DisruptionImpact | QualityImpact

    def __post_init__(self) -> None:
        if self.slot_board is None:
            self.slot_board = SlotBoard(self.world)
        if not self.event_id and self.event:
            self.event_id = self.event.get("id", "")

    # -- helpers used by the tools and the coordinator -----------------------------------------------------------
    def moved_po_ids(self) -> list[str]:
        return sorted({m.po.id for ms in self.moves.values() for m in ms.moves})

    def affected_co_ids(self) -> list[str]:
        """Customer orders of every proposed move (what notices and loaners are about)."""
        return sorted({co.id for po in self.moved_po_ids() for co in self.world.cos_by_po.get(po, [])})
